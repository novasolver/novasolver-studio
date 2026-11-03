"""Build an instant-answer model of the person's own case: choose numbers to vary and their ranges, Studio solves a
Sobol design one case at a time, checks the fit on points held out of it, and answers between the points in milliseconds.

The model is a Gaussian process (Matern 5/2, one length scale per parameter, a learned nugget, linear trend); on the
seven NovaSolver Flash data sets it beat the thin-plate spline, and dataset/blind_check.py confirmed it on new solves.
The error bar is the larger of Flash's left-out 95th percentile and the process's own sigma stretched to reach 95 % on
left-out points, so it widens where the data are far. It covers interpolation only: mesh error shows up separately, as
the convergence studies run at a few design points, reported for the mesh the model was trained on (the GCI alone
describes the fine mesh). Outside the ranges it refuses.

The builder is a detached process like a solver job, so it survives the AI client or the window closing, and every
finished point is on disk, so a stopped or interrupted build resumes where it was."""
from __future__ import annotations

import json
import math
import os
import secrets
import subprocess
import sys
import time
import warnings
from functools import lru_cache
from pathlib import Path

import numpy as np
import psutil

from .config import STUDIO_ROOT, workspace, worker_argv
from .store import StudioError, _write_json

MIN_POINTS, DEFAULT_POINTS, MAX_POINTS = 20, 60, 500
RELIABLE_POINTS = 60            # below this the bar fell short of 95 % in the Flash data sets
MAX_PARAMETERS = 5              # measured up to here
MAX_MESH_CHECKS = 5
MAX_FAILED_SHARE = 0.2
NOISE_FLOOR = 3e-5              # relative: below this the covariance is numerics and the bars collapse
JOB_TIMEOUT_S = 6 * 3600
RESUME_LOCK_S = 60
FRACTION = 0.37123              # a value inside the ranges no whole-number field accepts
SEED = 20261103
DEFAULT_OUTPUTS = {
    "structural": ("max_vm_pa", "max_disp_m"), "thermal": ("t_max_k", "t_min_k", "q_in_w"), "modal": ("frequency_hz",),
    "buckling": ("critical_load_n",), "electrostatic": ("capacitance_f", "e_max_v_m"),
    "current": ("resistance_ohm", "power_w", "t_max_k", "j_max_a_m2"), "flow3d": ("dp_pa", "flow_rate_m3s", "max_speed"),
    "conjugate": ("t_solid_max_k", "t_outlet_k"), "external": ("cd", "drag_n"), "cavity": ("umin_center", "max_speed"),
    "cavity_of": ("umin_center", "max_speed"), "channel_of": ("umax_outlet", "max_speed")}
UNITS = {"pa": "Pa", "m": "m", "k": "K", "n": "N", "hz": "Hz", "w": "W", "a": "A", "ohm": "ohm", "f": "F", "j": "J",
         "m3s": "m3/s", "a_m2": "A/m2", "v_m": "V/m", "speed": "m/s"}
NAMED_UNITS = {"umin_center": "m/s", "umax_outlet": "m/s"}     # no suffix to read the unit from


def _unit(key: str) -> str:
    if key in NAMED_UNITS:
        return NAMED_UNITS[key]
    for suffix, unit in sorted(UNITS.items(), key=lambda kv: -len(kv[0])):
        if key.endswith("_" + suffix):
            return unit
    return "-"


# ---------------------------------------------------------------- the fit

def _kernel(r2):
    """k(r), and the factor f with dk/dlog(l_d) = f * (delta_d / l_d)^2."""
    r = np.sqrt(r2)
    e = np.exp(-math.sqrt(5) * r)
    return (1 + math.sqrt(5) * r + 5 * r2 / 3) * e, (5 / 3) * (1 + math.sqrt(5) * r) * e


def _nll(th, D2, z):
    from scipy.linalg import cho_factor, cho_solve
    n, dim = len(z), D2.shape[-1]
    ell, sf, sn = np.exp(th[:dim]), math.exp(th[-2]), math.exp(th[-1])
    S = D2 / ell ** 2
    k, f = _kernel(S.sum(-1))
    try:
        cf = cho_factor(sf ** 2 * k + sn ** 2 * np.eye(n), lower=True, check_finite=False)
    except np.linalg.LinAlgError:
        return 1e25, np.zeros_like(th)
    a = cho_solve(cf, z, check_finite=False)
    W = cho_solve(cf, np.eye(n), check_finite=False) - np.outer(a, a)
    g = np.zeros_like(th)
    for d in range(dim):
        g[d] = 0.5 * (W * (sf ** 2 * f * S[..., d])).sum()
    g[-2] = (W * (sf ** 2 * k)).sum()
    g[-1] = sn ** 2 * np.trace(W)
    return 0.5 * z @ a + np.log(np.diag(cf[0])).sum() + 0.5 * n * math.log(2 * math.pi), g


class Fit:
    """One output over the unit box. `hyper` skips the learning (a saved model is rebuilt from its numbers)."""

    def __init__(self, U, y, floor: float, hyper: dict | None = None):
        from scipy.linalg import cho_factor, cho_solve
        from scipy.optimize import minimize
        U, y = np.asarray(U, float), np.asarray(y, float)
        self.U = U
        n, dim = U.shape
        A = np.c_[np.ones(n), U]
        self.beta = np.linalg.lstsq(A, y, rcond=None)[0]
        res = y - A @ self.beta
        self.scale = float(res.std()) or 1.0
        z = res / self.scale
        D2 = (U[:, None, :] - U[None, :, :]) ** 2
        self.floor = floor
        if hyper:
            th = np.log(np.r_[hyper["lengths"], hyper["signal"], hyper["noise"]])
        else:
            bounds = [(math.log(0.03), math.log(30))] * dim + [(math.log(1e-2), math.log(30)),
                                                               (min(math.log(floor / self.scale), math.log(0.5)), 0.0)]
            best = None
            for s in (0.7, 2.5):
                r = minimize(_nll, np.r_[np.full(dim, math.log(s)), 0.0, math.log(0.05)], args=(D2, z), jac=True,
                             method="L-BFGS-B", bounds=bounds, options={"maxiter": 200})
                if best is None or r.fun < best.fun:
                    best = r
            th = best.x
        self.ell, self.sf, self.sn = np.exp(th[:dim]), math.exp(th[-2]), math.exp(th[-1])
        K = self.sf ** 2 * _kernel((D2 / self.ell ** 2).sum(-1))[0] + self.sn ** 2 * np.eye(n)
        self.cf = cho_factor(K, lower=True, check_finite=False)
        self.a = cho_solve(self.cf, z, check_finite=False)
        d = np.diag(cho_solve(self.cf, np.eye(n), check_finite=False))
        i95 = min(n - 1, int(0.95 * n))
        self.half = float(np.sort(self.scale * np.abs(self.a / d))[i95])          # left-out residuals (Rippa)
        self.stretch = float(np.sort(np.abs(self.a) / np.sqrt(d))[i95])           # the same in units of sigma

    def predict(self, Us):
        from scipy.linalg import cho_solve
        Us = np.atleast_2d(np.asarray(Us, float))
        ks = self.sf ** 2 * _kernel((((Us[:, None, :] - self.U[None, :, :]) / self.ell) ** 2).sum(-1))[0]
        mean = ks @ self.a * self.scale + np.c_[np.ones(len(Us)), Us] @ self.beta
        v = self.sf ** 2 + self.sn ** 2 - (ks * cho_solve(self.cf, ks.T, check_finite=False).T).sum(1)
        sigma = self.scale * np.sqrt(np.maximum(v, self.sn ** 2))
        return mean, np.maximum(np.maximum(self.half, self.stretch * sigma), self.floor)

    def hyper(self) -> dict:
        return {"lengths": [float(v) for v in self.ell], "signal": self.sf, "noise": self.sn}


def transform(key: str, y) -> str:
    """Positive answers are fitted on their log, so the bar is relative. Temperatures keep an absolute bar in kelvin
    (one percent of 300 K says nothing), and anything that can cross zero stays linear."""
    return "log" if np.all(np.asarray(y) > 0) and _unit(key) != "K" else "linear"


def _forward(kind, y):
    return np.log(y) if kind == "log" else np.asarray(y, float)


def _floor(kind, y) -> float:
    return NOISE_FLOOR if kind == "log" else NOISE_FLOOR * max(float(np.abs(y).max()), 1e-30)


def fit_output(key: str, U, y, hold: int) -> dict:
    """Check on the last `hold` design points with a fit that never saw them, then fit on everything."""
    U, y = np.asarray(U, float), np.asarray(y, float)
    kind = transform(key, y)
    t, fl = _forward(kind, y), _floor(kind, y)
    out = {"key": key, "unit": _unit(key), "transform": kind, "points": len(y)}
    if hold:
        m, bar = Fit(U[:-hold], t[:-hold], fl).predict(U[-hold:])
        e = np.abs(m - t[-hold:])
        out["holdout"] = {"points": hold, "inside": int((e <= bar).sum()), **_error("max_error", kind, float(e.max()))}
    f = Fit(U, t, fl)
    out.update(hyper=f.hyper(), floor=fl, bar_95=_error("value", kind, f.half), y=[float(v) for v in y])
    return out


def _error(name: str, kind: str, bar: float) -> dict:
    return {f"{name}_pct": 100 * math.expm1(bar)} if kind == "log" else {f"{name}_abs": bar}


# ---------------------------------------------------------------- a study on disk

def studies_dir() -> Path:
    return workspace() / "surrogates"


def study_dir(study_id: str) -> Path:
    d = studies_dir() / study_id
    if not (study_id.startswith("s_") and study_id[2:].isalnum() and (d / "study.json").is_file()):
        raise StudioError("err.surrogate", 404, study_id=study_id)
    return d


def _read(path: Path) -> dict:
    for _ in range(40):                            # tolerate a concurrent atomic replace on Windows
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (PermissionError, json.JSONDecodeError):
            time.sleep(0.05)
    return json.loads(path.read_text(encoding="utf-8"))


def _points(d: Path) -> list[dict]:
    f = d / "points.jsonl"
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()] if f.is_file() else []


def _state(d: Path, **kw) -> dict:
    s = _read(d / "state.json")
    s.update(kw, updated_at=time.time())
    _write_json(d / "state.json", s)
    return s


def _alive(s: dict) -> bool:
    if not s.get("pid"):
        return False
    try:
        return abs(psutil.Process(s["pid"]).create_time() - s["pid_ctime"]) < 1.0
    except (psutil.Error, TypeError):
        return False


def _spawn(d: Path) -> None:
    env = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    backend = STUDIO_ROOT / "backend"
    if backend.is_dir():
        env["PYTHONPATH"] = str(backend)
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with open(d / "worker.log", "a", encoding="utf-8") as log:
        p = subprocess.Popen(worker_argv("novastudio.surrogate", str(d)), cwd=str(backend if backend.is_dir() else STUDIO_ROOT),
                             env=env, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=flags,
                             close_fds=True, start_new_session=(os.name != "nt"))
    try:
        ctime = psutil.Process(p.pid).create_time()
    except psutil.Error:
        ctime = None
    _state(d, state="running", pid=p.pid, pid_ctime=ctime, message=None)


def _claim(d: Path) -> bool:
    """One resume at a time: two builders on one study would solve the same points and delete the case under each other."""
    lock = d / "resume.lock"
    for _ in range(2):
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return True
        except (FileExistsError, PermissionError):
            try:
                if time.time() - lock.stat().st_mtime < RESUME_LOCK_S:
                    return False
                lock.unlink(missing_ok=True)       # left by a process that died holding it
            except OSError:
                pass
    return False


def _changes(study: dict, x) -> dict:
    return {p["path"]: ({"value": float(v), "unit": p["unit"]} if p.get("unit") else float(v))
            for p, v in zip(study["parameters"], x)}


def _value_at(p: dict, u: float) -> float:
    return p["min"] + u * (p["max"] - p["min"])


def _design(n: int, dim: int) -> np.ndarray:
    from scipy.stats import qmc
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")            # a Sobol run that is not a power of two: fine for this use
        u = qmc.Sobol(d=dim, scramble=True, seed=SEED).random(n)
    # without its data file scipy prints a note and returns the same point n times, and a model of one point looks perfect
    if any(len(np.unique(u[:, k])) < n for k in range(dim)):
        raise StudioError("err.surrogate_spec", 500, detail="the sampling plan repeated points")
    return u


def build(case_id: str, parameters: list[dict], outputs: list[str] | None = None, n: int | None = None,
          mesh_checks: int = 3, mode: str | None = None, lang: str = "ja") -> dict:
    """Freeze a copy of the case, check the ends of the ranges, and start the builder."""
    from . import checks, commands as C, store
    base = store.load(case_id)
    n = DEFAULT_POINTS if n is None else n
    if not (isinstance(parameters, list) and 1 <= len(parameters) <= MAX_PARAMETERS):
        raise StudioError("err.surrogate_spec", 400, detail=f"parameters: 1 to {MAX_PARAMETERS}")
    if not MIN_POINTS <= n <= MAX_POINTS:
        raise StudioError("err.surrogate_spec", 400, detail=f"n: {MIN_POINTS} to {MAX_POINTS}")
    if not 0 <= mesh_checks <= MAX_MESH_CHECKS:
        raise StudioError("err.surrogate_spec", 400, detail=f"mesh_checks: 0 to {MAX_MESH_CHECKS}")
    params = []
    for p in parameters:
        path, lo, hi = p.get("path"), p.get("min"), p.get("max")
        if not (isinstance(path, str) and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (lo, hi)) and lo < hi):
            raise StudioError("err.surrogate_spec", 400, detail=f"{path}: path, and finite min < max")
        params.append({"path": path, "min": float(lo), "max": float(hi), "unit": p.get("unit")})
    if len({p["path"] for p in params}) != len(params):
        raise StudioError("err.surrogate_spec", 400, detail="each path once")
    spec = {"parameters": params}
    # both ends of every range and a point between them must be valid cases; a wrong path, a unit or a whole-number field
    # fails here, not 60 solves later. Warnings stay with the study: a load a modal solve ignores varies nothing.
    made, setup_warnings = [], {}
    try:
        for u in (0.0, 1.0, FRACTION):
            pl = C.clone_case(case_id, {**_changes(spec, [_value_at(p, u) for p in params]), **({"run.mode": mode} if mode else {})},
                              "surrogate range check", lang, source="ai")
            made.append(pl["case"]["case_id"])
            found = checks.run(store.load(made[-1]), lang)
            items = [i["message"] for i in found if i["level"] == "error"]
            if items:
                raise StudioError("err.blocked", 400, items=items)
            setup_warnings.update({i["code"]: i["message"] for i in found if i["level"] == "warn"})
        frozen = C.clone_case(case_id, {"run.mode": mode} if mode else None, f"{base['title'][C.lang_of(lang)]} [surrogate base]", lang, source="ai")
    finally:
        for cid in made:
            _drop(cid, lang)
    sid = "s_" + secrets.token_hex(4)
    d = studies_dir() / sid
    d.mkdir(parents=True)
    from . import __version__
    study = {"study_id": sid, "base_case": case_id, "base_revision": base["revision"], "frozen_case": frozen["case"]["case_id"],
             "title": base["title"][C.lang_of(lang)], "parameters": params, "outputs": outputs, "n": n, "hold": max(5, n // 10),
             "mesh_checks": mesh_checks, "language": lang, "design": _design(n, len(params)).tolist(), "setup_warnings": setup_warnings,
             "created_at": time.time(), "studio_version": __version__}
    _write_json(d / "study.json", study)
    _write_json(d / "state.json", {"state": "starting", "pid": None, "pid_ctime": None, "updated_at": time.time()})
    _spawn(d)
    return status(sid)


def status(study_id: str | None = None) -> dict:
    if study_id is None:
        root = studies_dir()
        ids = sorted(p.parent.name for p in root.glob("s_*/study.json")) if root.is_dir() else []
        return {"studies": [status(i) for i in ids]}
    d = study_dir(study_id)
    st, sv = _read(d / "study.json"), _read(d / "state.json")
    pts = _points(d)
    design = [p for p in pts if p["kind"] == "design"]
    ok = [p for p in design if p["status"] == "ok"]
    state = sv["state"]
    if state == "running" and not _alive(sv):
        state = "interrupted"
    out = {"study_id": study_id, "title": st["title"], "state": state, "base_case": st["base_case"], "parameters": st["parameters"],
           "n": st["n"], "solved": len(ok), "failed": len(design) - len(ok), "message": sv.get("message"),
           "mesh_checks_done": sum(p["kind"] == "mesh" for p in pts), "mesh_checks": st["mesh_checks"], "setup_warnings": st["setup_warnings"],
           "failures": [p.get("error") for p in design if p["status"] != "ok"][-3:]}
    if state == "running" and ok:
        out["eta_s"] = round(np.mean([p["wall_s"] for p in ok]) * (st["n"] - len(design) + st["mesh_checks"] * 3))
    if (d / "model.json").is_file():
        m = _read(d / "model.json")
        out["model"] = {"path": str(d / "model.json"), "warnings": m["warnings"], "mesh": m["mesh"],
                        "outputs": [{k: o[k] for k in ("key", "unit", "transform", "points", "bar_95", "holdout") if k in o} for o in m["outputs"]]}
    return out


def control(study_id: str, action: str, confirm: str | None = None, lang: str = "ja") -> dict:
    d = study_dir(study_id)
    sv = _read(d / "state.json")
    if action == "stop":
        (d / "STOP").write_text("1")
        return status(study_id)
    if action == "resume":
        if not _claim(d):
            return status(study_id)
        try:
            sv = _read(d / "state.json")           # as it is now that nobody else can start one
            if sv["state"] != "done" and not _alive(sv):
                (d / "STOP").unlink(missing_ok=True)
                _spawn(d)
        finally:
            (d / "resume.lock").unlink(missing_ok=True)
        return status(study_id)
    if action == "delete":
        if confirm != study_id:
            raise StudioError("err.confirm", 400, case_id=study_id)
        if _alive(sv):
            (d / "STOP").write_text("1")
            psutil.Process(sv["pid"]).kill()
        cur = sv.get("current_case")
        for cid in {cur, _read(d / "study.json")["frozen_case"]} - {None}:
            _drop(cid, lang)
        import shutil
        shutil.rmtree(d, ignore_errors=True)
        _model.cache_clear()
        return {"deleted": study_id}
    raise StudioError("err.surrogate_spec", 400, detail=f"action={action} (stop|resume|delete)")


@lru_cache(maxsize=16)
def _loaded(path: str, _mtime: float) -> dict:
    m = _read(Path(path))
    U = np.array(m["U"], float)
    fits = {}
    for o in m["outputs"]:
        y = np.array(o["y"], float)
        fits[o["key"]] = Fit(U, _forward(o["transform"], y), o["floor"], o["hyper"])
    return {"meta": m, "fits": fits}


def _model(study_id: str) -> dict:
    f = study_dir(study_id) / "model.json"
    if not f.is_file():
        raise StudioError("err.surrogate_not_ready", 409, study_id=study_id)
    return _loaded(str(f), f.stat().st_mtime)


_model.cache_clear = _loaded.cache_clear


def predict(study_id: str, values: dict, outputs: list[str] | None = None) -> dict:
    mo = _model(study_id)
    m = mo["meta"]
    params = m["parameters"]
    names = [p["path"] for p in params]
    wrong = sorted(set(values) ^ set(names))
    if wrong:
        raise StudioError("err.surrogate_values", 400, names=", ".join(wrong), needs=", ".join(names))
    u = []
    for p in params:
        v = values[p["path"]]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise StudioError("err.estimate_value", 400, name=p["path"], value=v)
        if not p["min"] <= v <= p["max"]:
            raise StudioError("err.estimate_range", 400, name=p["path"], value=v, lo=p["min"], hi=p["max"])
        u.append((v - p["min"]) / (p["max"] - p["min"]))
    available = [o["key"] for o in m["outputs"]]
    unknown = sorted(set(outputs or ()) - set(available))
    if unknown:
        raise StudioError("err.surrogate_outputs", 400, names=", ".join(unknown), available=", ".join(available))
    rows = []
    for o in m["outputs"]:
        if outputs and o["key"] not in outputs:
            continue
        mean, bar = mo["fits"][o["key"]].predict([u])
        value = math.exp(mean[0]) if o["transform"] == "log" else float(mean[0])
        rows.append({"key": o["key"], "value": value, "unit": o["unit"], **_error("error", o["transform"], float(bar[0]))})
    d2 = ((np.array(m["U"]) - np.array(u)) ** 2).sum(1)
    return {"study_id": study_id, "title": m["title"], "values": values, "results": rows, "solved_points": len(m["U"]),
            "nearest_point": {p["path"]: _value_at(p, c) for p, c in zip(params, m["U"][int(d2.argmin())])},
            "mesh": m["mesh"], "warnings": m["warnings"]}


# ---------------------------------------------------------------- the builder process

def _stopped(d: Path) -> bool:
    return (d / "STOP").is_file()


def _numbers(metrics: dict) -> dict:
    return {k: float(v) for k, v in metrics.items() if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)}


def _drop(cid: str, lang: str, seconds: float = 30) -> bool:
    """Delete a temporary case. On Windows a solver that just ended can hold its log for a moment; a case that still
    will not go is left for the person to see rather than losing the build over it."""
    from . import commands as C
    end = time.time() + seconds
    while True:
        try:
            C.delete_case(cid, cid, lang)
            return True
        except StudioError:
            return False                           # already gone
        except OSError:
            if time.time() > end:
                return False
            time.sleep(0.5)


def _solve(d: Path, study: dict, x, title: str, convergence: bool = False) -> dict:
    """One clone, one job. The clone is deleted once its numbers are read."""
    from . import checks, commands as C, jobs, results, store
    lang = study["language"]
    pl = C.clone_case(study["frozen_case"], _changes(study, x), title, lang, source="ai")
    cid = pl["case"]["case_id"]
    _state(d, current_case=cid)
    try:
        case = store.load(cid)
        found = checks.run(case, lang)
        items = [i["message"] for i in found if i["level"] == "error"]
        if items:
            raise RuntimeError("; ".join(items))
        ready_warnings = {i["code"] for i in found if i["level"] == "warn"}
        t0 = time.time()
        job = jobs.start(case, case["run"]["mode"], checks.engine_for(case), **({"study": "convergence"} if convergence else {}))["job_id"]
        end = t0 + JOB_TIMEOUT_S
        j = jobs.status(job)
        while j["state"] not in jobs.TERMINAL:
            if _stopped(d) or time.time() > end:
                jobs.stop(job)
                return {"status": "stopped"} if _stopped(d) else {"status": "failed", "error": "timeout"}
            j = jobs.wait(job, 2)
        if j["state"] != "done":
            return {"status": "failed", "error": str(C.job_status(job, lang).get("first_error") or C.job_status(job, lang).get("message"))[:300]}
        _, raw = results.load(cid, job)
        pay = results.payload(store.load(cid), lang, job)
        if not pay["gates"]["converged"]:
            return {"status": "failed", "error": "not converged"}
        return {"status": "ok", "metrics": _numbers(raw["metrics"]), "result_kind": raw["kind"], "wall_s": round(time.time() - t0, 2),
                "warnings": sorted(ready_warnings | {w["code"] for w in pay["warnings"]}), "convergence": pay["convergence"],
                "mesh_size": case["mesh"]["size"]}
    finally:
        _drop(cid, lang)


def training_error(conv: dict, size: str) -> float | None:
    """How far the mesh the model learned from sits from the best estimate of that study, in percent. The GCI describes
    the fine mesh, and training usually runs on normal. None when there is nothing better than that mesh to compare with."""
    levels = {l["size"]: l["value"] for l in conv["levels"]}
    ref = conv.get("extrapolated")
    if ref is None:
        ref = conv["levels"][-1]["value"]
        if conv["levels"][-1]["size"] == size:
            return None
    if size not in levels or ref == 0:
        return None
    return abs(levels[size] - ref) / abs(ref) * 100


def _append(d: Path, row: dict) -> None:
    with (d / "points.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def _finish_model(d: Path, study: dict) -> None:
    pts = _points(d)
    ok = sorted((p for p in pts if p["kind"] == "design" and p["status"] == "ok"), key=lambda p: p["i"])
    keys = study["outputs"] or [k for k in DEFAULT_OUTPUTS.get(ok[0]["result_kind"], ()) if k in ok[0]["metrics"]]
    missing = sorted({k for k in keys for p in ok if k not in p["metrics"]})
    if missing or not keys:
        raise StudioError("err.surrogate_outputs", 400, names=", ".join(missing) or "-", available=", ".join(sorted(ok[0]["metrics"])))
    U = [study["design"][p["i"]] for p in ok]
    hold = min(study["hold"], len(ok) // 5)
    outs = [fit_output(k, U, [p["metrics"][k] for p in ok], hold) for k in keys]
    warn = []
    if len(ok) < RELIABLE_POINTS:
        warn.append("few_points")
    failed = sum(p["kind"] == "design" and p["status"] != "ok" for p in pts)
    if failed:
        warn.append("failed_points")
    if any(o.get("holdout") and o["holdout"]["inside"] < 0.8 * o["holdout"]["points"] for o in outs):
        warn.append("holdout_low")
    warn += sorted({w for p in ok for w in p["warnings"]})
    checks_ = [p for p in pts if p["kind"] == "mesh"]
    if checks_ and not all(p.get("mesh_pass") for p in checks_):
        warn.append("mesh_check_failed")
    if not checks_:
        warn.append("mesh_unchecked")
    gci = [p["gci_pct"] for p in checks_ if p.get("gci_pct") is not None]
    trained = [p["training_error_pct"] for p in checks_ if p.get("training_error_pct") is not None]
    model = {"study_id": study["study_id"], "title": study["title"], "base_case": study["base_case"], "base_revision": study["base_revision"],
             "studio_version": study["studio_version"], "built_at": time.time(), "parameters": study["parameters"], "U": U, "outputs": outs,
             "warnings": warn, "failed_points": failed,
             "mesh": {"checks": len(checks_), "quantity": next((p.get("gci_quantity") for p in checks_), None),
                      "gci_max_pct": max(gci) if gci else None, "passed": sum(bool(p.get("mesh_pass")) for p in checks_),
                      "training_size": ok[0].get("mesh_size"), "training_error_max_pct": max(trained) if trained else None}}
    _write_json(d / "model.json", model)


def main(folder: str) -> None:
    from . import commands as C
    d = Path(folder)
    study = _read(d / "study.json")
    lang = study["language"]
    try:
        pts = _points(d)
        done = {p["i"] for p in pts if p["kind"] == "design"}
        stale = _read(d / "state.json").get("current_case")   # left behind by an interrupted build
        if stale:
            _drop(stale, lang)
        for i, u in enumerate(study["design"]):
            if i in done:
                continue
            if _stopped(d):
                _state(d, state="stopped", pid=None)
                return
            x = [_value_at(p, c) for p, c in zip(study["parameters"], u)]
            r = _solve(d, study, x, f"{study['title']} [surrogate {i + 1}/{study['n']}]")
            if r["status"] == "stopped":
                _state(d, state="stopped", pid=None)
                return
            _append(d, {"kind": "design", "i": i, "x": x, **{k: v for k, v in r.items() if k != "convergence"}})
            pts = _points(d)
            bad = sum(p["kind"] == "design" and p["status"] != "ok" for p in pts)
            if bad >= 5 and bad > MAX_FAILED_SHARE * sum(p["kind"] == "design" for p in pts):
                last = next(p["error"] for p in reversed(pts) if p["kind"] == "design" and p["status"] != "ok")
                _state(d, state="failed", pid=None, message=f"too many failed solves: {last}")
                return
        mesh_done = {p["i"] for p in _points(d) if p["kind"] == "mesh"}
        for i in np.linspace(0, study["n"] - 1, study["mesh_checks"]).astype(int).tolist() if study["mesh_checks"] else []:
            if i in mesh_done:
                continue
            if _stopped(d):
                _state(d, state="stopped", pid=None)
                return
            x = [_value_at(p, c) for p, c in zip(study["parameters"], study["design"][i])]
            r = _solve(d, study, x, f"{study['title']} [surrogate mesh check]", convergence=True)
            if r["status"] == "stopped":
                _state(d, state="stopped", pid=None)
                return
            v = r.get("convergence") or {}
            _append(d, {"kind": "mesh", "i": i, "x": x, "status": r["status"], "error": r.get("error"), "gci_pct": v.get("gci_pct"),
                        "gci_quantity": v.get("label"), "mesh_pass": bool(v.get("pass")),
                        "training_error_pct": training_error(v, r["mesh_size"]) if v else None})
        if not any(p["kind"] == "design" and p["status"] == "ok" for p in _points(d)):
            _state(d, state="failed", pid=None, message="no point was solved")
            return
        _finish_model(d, study)
        _drop(study["frozen_case"], lang)
        _state(d, state="done", pid=None, current_case=None)
    except StudioError as e:
        _state(d, state="failed", pid=None, message=C.error_payload(e, lang)["message"])
    except Exception as e:
        _state(d, state="failed", pid=None, message=f"{type(e).__name__}: {e}"[:400])
        raise


if __name__ == "__main__":
    main(sys.argv[1])
