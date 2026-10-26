"""Solver job process:  python -m novastudio.run_worker <job_dir>

Reads request.json (case snapshot, mode, engine), runs the engine, writes results.json (numbers + gates)
and results.npz (fields), and keeps job.json updated so GUI and AI can follow progress.
"""
from __future__ import annotations

import json
import math
import sys
import time
import traceback
from pathlib import Path

import numpy as np

from . import units
from .jobs import read, update
from .store import _write_json


def _progress(jd: Path):
    def f(key: str, frac: float, args: dict | None = None):
        update(jd, state="running", progress=round(float(frac), 3), message_key=key, message_args=args or {})
    return f


DIR_VEC = {"-x": [-1, 0, 0], "+x": [1, 0, 0], "-y": [0, -1, 0], "+y": [0, 1, 0], "-z": [0, 0, -1], "+z": [0, 0, 1]}


def _mesh_for_run(case: dict, jd: Path, prog):
    from . import geometry
    from .store import case_dir
    import shutil
    if case.get("_mesh_dir"):                       # convergence study level: always mesh into its own folder
        prog("job.meshing", 0.03)
        geometry.generate_mesh(case)
    else:
        ms = geometry.mesh_state(case)
        if not ms["exists"] or ms["stale"]:
            prog("job.meshing", 0.03)
            geometry.generate_mesh(case)
    shutil.copyfile(geometry.mesh_dir(case) / "mesh.npz", jd / "mesh.npz")   # results stay tied to their mesh
    m = dict(np.load(jd / "mesh.npz"))
    check_condition_faces(case, m)
    return m


PASSIVE_ROLES = {None, "free", "insulated", "wall"}   # the default role of each physics: no condition to lose


def check_condition_faces(case: dict, m: dict) -> None:
    """Every face that carries a condition must be in the mesh. Otherwise the solver would quietly run without that
    support or load and report a converged but meaningless answer (seen when a remesh lost a face's name)."""
    from .store import StudioError
    lost = sorted(k for k, b in case.get("boundaries", {}).items()
                  if b.get("role") not in PASSIVE_ROLES and len(m.get(f"face_{k}", ())) == 0)
    if lost:
        raise StudioError("err.face_lost", 500, faces=", ".join(lost))


def structural_loads(case: dict, m: dict):
    """Fixed faces and per-triangle tractions [Pa] for every face role. Shared by the built-in solver and CalculiX."""
    from .fem_tet10 import canonical_tets, outward_normals, tri_areas
    nodes = m["nodes"]
    tets = canonical_tets(nodes, m["tets"])
    fixed, tractions = [], []
    for face, b in case["boundaries"].items():
        tri = m.get(f"face_{face}")
        if tri is None or b["role"] in ("free", None):
            continue
        if b["role"] == "fixed":
            fixed.append(tri)
            continue
        area = tri_areas(nodes, tri)
        if b["role"] == "load":
            F = units.to_si(b["force"])
            d = b.get("direction", "-z")
            if d == "normal":
                vec = -outward_normals(nodes, tets, tri)            # pushes into the face
            else:
                vec = np.broadcast_to(np.array(DIR_VEC[d], float), (len(tri), 3))
            tractions.append((tri, vec * F / area.sum()))
        elif b["role"] == "pressure":
            p = units.to_si(b["pressure"])
            tractions.append((tri, -p * outward_normals(nodes, tets, tri)))
    return fixed, tractions


def support_peak(nodes: np.ndarray, fixed: list, vm: np.ndarray) -> dict:
    """Is the peak stress at the edge of a fully fixed face? There the stress is theoretically infinite (a rigid
    support is a singularity), so the peak means nothing. Also return the peak a couple of elements away from the
    supports, which is the number to judge strength by."""
    if not fixed:
        return {}
    from scipy.spatial import cKDTree
    tri = np.concatenate([np.asarray(f)[:, :3] for f in fixed])
    fx = nodes[np.unique(tri)]
    edge = np.linalg.norm(nodes[tri[:, 0]] - nodes[tri[:, 1]], axis=1)
    reach = 2.0 * float(np.median(edge))                        # about two elements
    dist, _ = cKDTree(fx).query(nodes)
    away = dist > reach
    peak_on_support = bool(dist[int(np.argmax(vm))] <= reach)
    out = {"peak_on_support": peak_on_support}
    if away.any():
        out["max_vm_away_pa"] = float(vm[away].max())
    return out


def run_structural_builtin(case: dict, jd: Path, prog) -> dict:
    from . import fem_tet10
    m = _mesh_for_run(case, jd, prog)
    nodes, tets = m["nodes"], m["tets"]
    mat = case["materials"]["solid"]
    E, nu = units.to_si(mat["E"]), units.to_si(mat["nu"])
    fixed, tractions = structural_loads(case, m)
    r = fem_tet10.solve(nodes, tets, E, nu, fixed, tractions, progress=lambda k, f: prog(k, f))
    U = r["u"]
    umag = np.linalg.norm(U, axis=1)
    np.savez_compressed(jd / "results.npz", u=U, vm=r["vm"])
    metrics = {"max_vm_pa": float(r["vm"].max()), "max_disp_m": float(umag.max()),
               "reaction_n": float(np.linalg.norm(r["reaction"])), "applied_n": float(np.linalg.norm(r["applied"])),
               "imbalance": r["imbalance"], "nodes": int(len(nodes)), "elements": int(len(tets))}
    metrics.update(support_peak(nodes, fixed, r["vm"]))
    if case["template"] == "cantilever":
        metrics["tip_disp_m"] = float(-U[np.unique(m["face_x1"]), 2].mean())
        ref = reference_cantilever(case, metrics["tip_disp_m"])
    elif case["template"] == "plate-hole":
        ref = reference_plate_hole(case, m["nodes"], r["vm"], metrics)
    else:
        ref = {"applicable": False, "why": "no analytic reference for this shape; compare a 'fine' mesh run to check convergence"}
    converged = bool(r["imbalance"] < 5e-3 and np.isfinite(umag).all())
    return {"kind": "structural", "metrics": metrics, "converged": converged,
            "converged_detail": {"imbalance": r["imbalance"], "limit": 5e-3}, "reference": ref}


def thermal_groups(case: dict, m: dict):
    fixed, fluxes, conv, order = [], [], [], {"fixed": [], "flux": [], "convection": []}
    for face, b in case["boundaries"].items():
        tri = m.get(f"face_{face}")
        if tri is None:
            continue
        if b["role"] == "temperature":
            fixed.append((tri, units.to_si(b["temperature"]))); order["fixed"].append(face)
        elif b["role"] == "heat-flux":
            fluxes.append((tri, units.to_si(b["flux"]))); order["flux"].append(face)
        elif b["role"] == "convection":
            conv.append((tri, units.to_si(b["h"]), units.to_si(b["tinf"]))); order["convection"].append(face)
    return fixed, fluxes, conv, order


def run_thermal_builtin(case: dict, jd: Path, prog) -> dict:
    from . import fem_tet10
    m = _mesh_for_run(case, jd, prog)
    k = units.to_si(case["materials"]["solid"]["k"])
    fixed, fluxes, conv, order = thermal_groups(case, m)
    r = fem_tet10.solve_thermal(m["nodes"], m["tets"], k, fixed, fluxes, conv, progress=lambda kk, f: prog(kk, f))
    T = r["T"]
    np.savez_compressed(jd / "results.npz", T=T)
    face_flows = {face: q for g in ("fixed", "flux", "convection") for face, q in zip(order[g], r["flows"][g])}
    metrics = {"t_max_k": float(np.nanmax(T)), "t_min_k": float(np.nanmin(T)), "q_in_w": r["total_in"],
               "imbalance": r["imbalance"], "face_flows_w": face_flows,
               "nodes": int(len(m["nodes"])), "elements": int(len(m["tets"]))}
    ref = reference_thermal_block(case, face_flows) if case["template"] == "thermal-block" else \
        reference_fin(case, face_flows) if case["template"] == "fin" else \
        {"applicable": False, "why": "no analytic reference for this shape; compare a 'fine' mesh run to check convergence"}
    return {"kind": "thermal", "metrics": metrics, "converged": bool(r["imbalance"] < 1e-3 and np.isfinite(T).all()),
            "converged_detail": {"heat_balance_error": r["imbalance"], "limit": 1e-3}, "reference": ref}


def reference_thermal_block(case: dict, face_flows: dict) -> dict:
    b = case["boundaries"]
    ok = b["x0"]["role"] == "temperature" and b["x1"]["role"] == "temperature" and \
        all(b[f]["role"] == "insulated" for f in ("y0", "y1", "z0", "z1"))
    if not ok:
        return {"applicable": False, "why": "1D conduction reference needs x0/x1 fixed temperatures and the other faces insulated"}
    p = case["geometry"]["params"]
    L, w, h = (units.to_si(p[x]) for x in ("length", "width", "height"))
    k = units.to_si(case["materials"]["solid"]["k"])
    dT = units.to_si(b["x0"]["temperature"]) - units.to_si(b["x1"]["temperature"])
    ref = k * w * h * dT / L
    q = face_flows.get("x0", 0.0)
    err = (q - ref) / ref * 100 if ref else 0.0
    return {"applicable": True, "quantity": "heat_flow", "reference": ref, "computed": q, "unit": "W", "error_pct": err,
            "tolerance_pct": case["reference"]["tolerance_pct"], "pass": abs(err) <= case["reference"]["tolerance_pct"],
            "formula": "Q = k A (T_hot - T_cold) / L"}

def reference_plate_hole(case: dict, nodes, vm, metrics: dict) -> dict:
    """Net-section stress concentration factor vs Heywood: Kt_n = 2 + (1 - d/W)^3 (uniaxial tension, finite width)."""
    b = case["boundaries"]
    ok = b["x0"]["role"] == "fixed" and b["x1"]["role"] == "load" and b["x1"].get("direction") == "+x" and \
        all(b[k]["role"] == "free" for k in ("y0", "y1", "z0", "z1", "hole"))
    if not ok:
        return {"applicable": False, "why": "Heywood reference needs x0 fixed, +x tension on x1, all other faces free"}
    p = case["geometry"]["params"]
    L, W, t, d = (units.to_si(p[k]) for k in ("length", "width", "thickness", "hole"))
    F = units.to_si(b["x1"]["force"])
    r = np.hypot(nodes[:, 0] - L / 2, nodes[:, 1] - W / 2)
    near = r < 1.5 * d                                           # ignore the clamped end; the peak sits at the hole
    smax = float(vm[near].max())
    s_net = F / ((W - d) * t)
    kt = smax / s_net
    kt_ref = 2 + (1 - d / W) ** 3
    err = (kt - kt_ref) / kt_ref * 100
    metrics["kt"] = kt
    return {"applicable": True, "quantity": "kt", "reference": kt_ref, "computed": kt, "unit": "-", "error_pct": err,
            "tolerance_pct": case["reference"]["tolerance_pct"], "pass": abs(err) <= case["reference"]["tolerance_pct"],
            "metric": "Kt_net = max von Mises at the hole / (F / ((W - d) t)); Heywood: 2 + (1 - d/W)^3"}


def reference_fin(case: dict, face_flows: dict) -> dict:
    """Heat through the base of a straight fin with a convective tip (1D fin theory)."""
    b = case["boundaries"]
    sides = ("x1", "y0", "y1", "z0", "z1")
    ok = b["x0"]["role"] == "temperature" and all(b[k]["role"] == "convection" for k in sides)
    hs = {units.to_si(b[k]["h"]) for k in sides} if ok else set()
    ts = {units.to_si(b[k]["tinf"]) for k in sides} if ok else set()
    if not ok or len(hs) != 1 or len(ts) != 1:
        return {"applicable": False, "why": "fin reference needs a fixed-temperature base and the same convection on all other faces"}
    p = case["geometry"]["params"]
    L, w, hh = (units.to_si(p[k]) for k in ("length", "width", "height"))
    k = units.to_si(case["materials"]["solid"]["k"])
    h, tinf = hs.pop(), ts.pop()
    P, A = 2 * (w + hh), w * hh
    m = math.sqrt(h * P / (k * A))
    theta = units.to_si(b["x0"]["temperature"]) - tinf
    a = h / (m * k)
    q_ref = math.sqrt(h * P * k * A) * theta * (math.sinh(m * L) + a * math.cosh(m * L)) / (math.cosh(m * L) + a * math.sinh(m * L))
    q = face_flows.get("x0", 0.0)
    err = (q - q_ref) / q_ref * 100 if q_ref else 0.0
    return {"applicable": True, "quantity": "heat_flow", "reference": q_ref, "computed": q, "unit": "W", "error_pct": err,
            "tolerance_pct": case["reference"]["tolerance_pct"], "pass": abs(err) <= case["reference"]["tolerance_pct"],
            "metric": "Q = sqrt(hPkA) θb (sinh mL + (h/mk) cosh mL) / (cosh mL + (h/mk) sinh mL)"}


def reference_cantilever(case: dict, tip: float) -> dict:
    b = case["boundaries"]
    pattern_ok = b["x0"]["role"] == "fixed" and b["x1"]["role"] == "load" and \
        all(b[k]["role"] == "free" for k in ("y0", "y1", "z0", "z1"))
    p = case["geometry"]["params"]
    L, w, h = units.to_si(p["length"]), units.to_si(p["width"]), units.to_si(p["height"])
    mat = case["materials"]["solid"]
    E, nu = units.to_si(mat["E"]), units.to_si(mat["nu"])
    tol = case["reference"]["tolerance_pct"]
    if not pattern_ok:
        return {"applicable": False, "why": "boundary pattern differs from the textbook cantilever (x0 fixed, x1 load, others free)"}
    F = units.to_si(b["x1"]["force"])
    I = w * h**3 / 12
    G = E / (2 * (1 + nu))
    kappa = 10 * (1 + nu) / (12 + 11 * nu)
    ref = F * L**3 / (3 * E * I) + F * L / (kappa * G * w * h)
    err = (tip - ref) / ref * 100 if ref else 0.0
    return {"applicable": True, "quantity": "tip_disp", "reference": ref, "computed": tip, "unit": "m",
            "error_pct": err, "tolerance_pct": tol, "pass": abs(err) <= tol,
            "formula": "F L^3/(3 E I) + F L/(kappa G A), kappa = 10(1+nu)/(12+11nu)"}


def run_cavity_builtin(case: dict, jd: Path, prog) -> dict:
    from . import cavity_fd
    L = units.to_si(case["geometry"]["params"]["size"])
    Ulid = units.to_si(case["boundaries"]["y1"]["speed"]) if case["boundaries"]["y1"]["role"] == "moving-wall" else 0.0
    nu = units.to_si(case["materials"]["fluid"]["nu"])
    re = Ulid * L / nu if nu > 0 else 0.0
    if Ulid <= 0 or re <= 0:
        raise ValueError("the lid (y1) must be a moving wall with a positive speed")
    stop_flag = jd / "STOP"
    r = cavity_fd.solve(re, case["mesh"]["size"], progress=lambda k, f, a: prog(k, f, a),
                        should_stop=lambda: stop_flag.exists())
    e = cavity_fd.ghia_error(r)
    np.savez_compressed(jd / "results.npz", x=r["x"], psi=r["psi"], u=r["u"], v=r["v"], L=L, U=Ulid)
    speed = np.hypot(r["u"], r["v"]) * Ulid
    metrics = {"re": re, "umin_center": e["u_min"] * Ulid, "max_speed": float(speed.max()), "iterations": r["iterations"],
               "residual": r["residual"], "nodes": r["n"] ** 2, "elements": (r["n"] - 1) ** 2}
    b = case["boundaries"]
    pattern_ok = all(b[k]["role"] == "wall" for k in ("x0", "x1", "y0"))
    tol = case["reference"]["tolerance_pct"]
    if abs(re - 100) / 100 > 0.01 or not pattern_ok:
        ref = {"applicable": False, "why": "Ghia reference data is for Re = 100 with three stationary walls"}
    else:
        err_pct = e["mean_abs"] * 100          # mean |u - u_ghia| as % of the lid speed
        ref = {"applicable": True, "quantity": "u_centerline", "reference": e["u_min_ref"] * Ulid,
               "computed": e["u_min"] * Ulid, "unit": "m/s", "error_pct": err_pct, "tolerance_pct": tol,
               "pass": err_pct <= tol, "points": e["points"], "metric": "mean |u - u_Ghia| / U_lid"}
    return {"kind": "cavity", "metrics": metrics, "converged": bool(r["converged"]),
            "converged_detail": {"residual": r["residual"], "limit": 1e-5}, "reference": ref,
            "history": r["history"]}


# ------------------------------------------------------------------ mesh convergence study

def primary_quantity(case: dict, res: dict) -> tuple[str, float, str]:
    """The one number a mesh study tracks (name, value in SI, unit)."""
    m = res["metrics"]
    k = res["kind"]
    if k == "structural":
        return ("max_disp", m["max_disp_m"], "m")
    if k == "thermal":
        n_fixed = sum(1 for b in case["boundaries"].values() if b.get("role") == "temperature")
        if n_fixed >= 2 and m.get("q_in_w") is not None:
            return ("q_in", m["q_in_w"], "W")
        return ("t_rise", m["t_max_k"] - m["t_min_k"], "K")
    if k == "flow3d":
        return ("dp", m["dp_pa"], "Pa")
    if k == "external":
        return ("cd", m["cd"], "-")
    if k in ("cavity", "cavity_of"):
        return ("umin_center", m["umin_center"], "m/s")
    raise ValueError(f"no study quantity for {k}")


def gci(levels: list[dict], fs: float = 1.25) -> dict:
    """Roache's Grid Convergence Index from three meshes (coarse -> fine), h ~ N^(-1/3)."""
    (h1, f1), (h2, f2), (h3, f3) = [(l["h"], l["value"]) for l in levels]
    r21, r32 = h1 / h2, h2 / h3
    e21, e32 = f2 - f1, f3 - f2
    monotone = e21 * e32 > 0 and abs(e32) > 0
    asymptotic = False
    if monotone:
        r = math.sqrt(r21 * r32)
        p = math.log(abs(e21 / e32)) / math.log(r)
        asymptotic = p >= 1.0
        if not asymptotic:
            # error is not shrinking as the mesh refines: not in the asymptotic range. Use p = 1 with the
            # conservative safety factor and do not trust Richardson extrapolation.
            p, fs = 1.0, 3.0
        p = min(p, 4.0)
    else:
        p, fs = 2.0, 3.0                         # oscillatory or exact: conservative safety factor
    denom = r32 ** p - 1
    rel = abs(e32 / f3) if f3 else 0.0
    gci_fine = fs * rel / denom * 100 if denom > 0 else rel * 100
    f_ext = f3 + e32 / denom if denom > 0 else f3
    if not asymptotic:
        f_ext = None
    return {"p": p, "monotone": monotone, "asymptotic": asymptotic, "gci_pct": gci_fine, "f_ext": f_ext,
            "rel_change_pct": rel * 100,
            "r21": r21, "r32": r32, "safety_factor": fs}


def run_study(req: dict, jd: Path, prog) -> dict:
    import copy
    import shutil
    from .templates import get as tpl
    case = req["case"]
    eng = req["engine"]
    if eng == "builtin-fem" and tpl(case["template"])["physics"] == "thermal":
        eng = "builtin-thermal"
    fn = ENGINES.get(eng)
    levels = []
    for i, size in enumerate(("coarse", "normal", "fine")):
        sub = jd / "levels" / size
        sub.mkdir(parents=True, exist_ok=True)
        snap = copy.deepcopy(case)
        snap["mesh"]["size"] = size
        snap["_mesh_dir"] = str(sub / "mesh")
        lo, hi = i / 3, (i + 1) / 3
        sp = lambda key, frac, args=None, lo=lo, hi=hi: prog(key, lo + (hi - lo) * frac, args)
        if fn is None:
            from . import external
            res = external.run(eng, snap, sub, sp)
        else:
            res = fn(snap, sub, sp)
        name, val, unit = primary_quantity(snap, res)
        n = res["metrics"].get("elements") or 1
        levels.append({"size": size, "elements": n, "h": n ** (-1 / 3), "value": val, "converged": res["converged"],
                       "peak_vm_pa": res["metrics"].get("max_vm_pa")})
        _write_json(sub / "results.json", res)
    g = gci(levels)
    tol = 5.0
    # a study only means something if the mesh really got finer; identical meshes would "agree" perfectly
    refined = all(b["elements"] >= 1.3 * a["elements"] for a, b in zip(levels, levels[1:]))
    passed = all(l["converged"] for l in levels) and g["gci_pct"] <= tol and refined
    fine = json.loads((jd / "levels" / "fine" / "results.json").read_text(encoding="utf-8"))
    for f in ("results.npz", "mesh.npz"):
        if (jd / "levels" / "fine" / f).is_file():
            shutil.copyfile(jd / "levels" / "fine" / f, jd / f)
    conv = {"quantity": name, "unit": unit, "levels": levels, **g, "tolerance_pct": tol, "pass": passed,
            "refined": refined}
    peaks = [l.get("peak_vm_pa") for l in levels]
    if all(peaks):
        # a peak that keeps rising with every refinement is a stress singularity (sharp re-entrant corner, edge of a
        # rigid support): the displacement converges, the peak stress never will. Say so instead of hiding it.
        rise = (peaks[2] - peaks[1]) / peaks[1]
        conv["peak_stress"] = {"levels_pa": peaks, "rise_fine_pct": rise * 100,
                               "singular": peaks[0] < peaks[1] < peaks[2] and rise > 0.03}
    fine["convergence"] = conv
    if not (fine.get("reference") or {}).get("applicable"):
        # no analytic reference: the mesh study is the verification (solution verification, Roache/ASME V&V 20)
        fine["reference"] = {"applicable": True, "kind": "convergence", "quantity": name,
                             "reference": g["f_ext"] if g["f_ext"] is not None else levels[-1]["value"],
                             "computed": levels[-1]["value"], "unit": unit, "error_pct": g["gci_pct"],
                             "tolerance_pct": tol, "pass": passed, "metric": "GCI (fine mesh)"}
    return fine

ENGINES = {"builtin-fem": run_structural_builtin, "builtin-cavity": run_cavity_builtin, "builtin-thermal": run_thermal_builtin}


def _acquire_solver_slot(jd: Path) -> Path:
    """One solver job at a time on this machine (meshes and solvers can each use many GB on a 16 GB PC).
    The slot is a directory created atomically; a slot left by a dead process is reclaimed."""
    import os
    import psutil
    # machine-wide (not per workspace): every Studio workspace on this PC shares the same memory
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "NovaSolverStudio"
    base.mkdir(parents=True, exist_ok=True)
    slot = base / "solver.lock"
    while True:
        try:
            os.mkdir(slot)
            (slot / "owner.json").write_text(json.dumps({"pid": os.getpid(), "job": jd.name,
                                                         "ctime": psutil.Process().create_time()}))
            return slot
        except FileExistsError:
            o = {}
            try:
                o = json.loads((slot / "owner.json").read_text())
                alive = psutil.pid_exists(o["pid"]) and abs(psutil.Process(o["pid"]).create_time() - o["ctime"]) < 1
            except Exception:
                alive = (time.time() - slot.stat().st_mtime) < 10      # owner file not written yet
            if not alive:
                import shutil
                shutil.rmtree(slot, ignore_errors=True)
                continue
            if (jd / "STOP").exists():
                raise RuntimeError("stopped while waiting for another job")
            update(jd, state="queued", message_key="job.waiting", message_args={"other": o.get("job", "")})
            time.sleep(1.0)


def _release_solver_slot(slot: Path) -> None:
    import shutil
    shutil.rmtree(slot, ignore_errors=True)


def main(job_dir: str) -> None:
    jd = Path(job_dir)
    req = json.loads((jd / "request.json").read_text(encoding="utf-8"))
    prog = _progress(jd)
    t0 = time.time()
    lock = None
    try:
        lock = _acquire_solver_slot(jd)
        t0 = time.time()
        prog("job.running", 0.01)
        from .templates import get as _tp
        eng = req["engine"]
        if eng == "builtin-fem" and _tp(req["case"]["template"])["physics"] == "thermal":
            eng = "builtin-thermal"
        fn = ENGINES.get(eng)
        if req.get("study") == "convergence":
            res = run_study(req, jd, prog)
        elif fn is None:
            from . import external
            res = external.run(req["engine"], req["case"], jd, prog)
        else:
            res = fn(req["case"], jd, prog)
        res.update({"engine": req["engine"], "mode": req["mode"], "ran": True, "wall_s": round(time.time() - t0, 2),
                    "revision": req["case"]["revision"]})
        _write_json(jd / "results.json", res)
        if read(jd)["state"] != "stopped":
            update(jd, state="done", progress=1.0, message_key="job.done", message_args={})
    except Exception as exc:  # report the first useful line to the user/model
        tb = traceback.format_exc()
        (jd / "error.txt").write_text(tb, encoding="utf-8")
        if (jd / "STOP").exists():                 # stopped by the user (while waiting or running): not a failure
            update(jd, state="stopped", message_key="job.stopped", message_args={})
        elif getattr(exc, "key", "").startswith("err."):    # a StudioError: its own translated message
            update(jd, state="failed", message_key=exc.key, message_args={k: str(v) for k, v in exc.kw.items()})
        else:
            update(jd, state="failed", message_key="err.solver", message_args={"detail": f"{type(exc).__name__}: {exc}"})
    finally:
        if lock is not None:
            _release_solver_slot(lock)


if __name__ == "__main__":
    main(sys.argv[1])
