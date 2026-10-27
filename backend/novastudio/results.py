"""Results: gates, number cards, verification line, viewer fields and PNG renders.
Raw numbers come from <run>/results.json and results.npz written by the worker; this module only presents them."""
from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np

from . import geometry, units
from .i18n import lang_of, t
from .store import StudioError, case_dir

QUANTITIES = {
    "structural": [("vm", "MPa", "sequential"), ("disp", "mm", "sequential"), ("uz", "mm", "diverging")],   # stress first: what decides failure
    "thermal": [("temp", "°C", "sequential")],
    "conjugate": [("temp", "°C", "sequential"), ("speed", "m/s", "sequential")],
    "flow3d": [("speed", "m/s", "sequential"), ("p", "Pa", "sequential")],
    "external": [("speed", "m/s", "sequential"), ("p", "Pa", "diverging")],
    "cavity": [("speed", "m/s", "sequential"), ("ux", "m/s", "diverging"), ("psi", "m2/s", "diverging")],
    "cavity_of": [("speed", "m/s", "sequential"), ("ux", "m/s", "diverging")],
    "channel_of": [("speed", "m/s", "sequential"), ("ux", "m/s", "diverging")],
}


def latest_done_run(case_id: str, run_id: str | None = None) -> Path | None:
    rd = case_dir(case_id) / "run"
    if not rd.is_dir():
        return None
    runs = [rd / run_id] if run_id else sorted(rd.glob("r_*"), reverse=True)
    for jd in runs:
        if (jd / "results.json").is_file():
            return jd
    return None


def load(case_id: str, run_id: str | None = None) -> tuple[Path, dict]:
    jd = latest_done_run(case_id, run_id)
    if jd is None:
        raise StudioError("err.no_results", 404)
    return jd, json.loads((jd / "results.json").read_text(encoding="utf-8"))


def _card(key, value, unit, lang, digits=4):
    return {"key": key, "label": t(f"card.{key}", lang), "value": float(f"{value:.{digits}g}"), "unit": unit}


def payload(case: dict, lang: str, run_id: str | None = None) -> dict:
    jd, r = load(case["case_id"], run_id)
    m = r["metrics"]
    cards = []
    if r["kind"] == "structural":
        cards = [_card("tip_disp", m["tip_disp_m"] * 1e3, "mm", lang)] if "tip_disp_m" in m else []
        if "kt" in m:
            cards.append(_card("kt", m["kt"], "-", lang))
        cards += [_card("max_vm", m["max_vm_pa"] / 1e6, "MPa", lang), _card("max_disp", m["max_disp_m"] * 1e3, "mm", lang)]
        if "reaction_n" in m:
            cards.append(_card("reaction", m["reaction_n"], "N", lang))
    elif r["kind"] in ("cavity", "cavity_of"):
        cards = [_card("re", m["re"], "-", lang), _card("umin_center", m["umin_center"], "m/s", lang),
                 _card("max_speed", m["max_speed"], "m/s", lang)]
        if "iterations" in m:
            cards.append(_card("iterations", m["iterations"], "-", lang, 6))
    elif r["kind"] == "external":
        cards = [_card("cd", m["cd"], "-", lang), _card("drag", m["drag_n"], "N", lang), _card("cl", m["cl"], "-", lang),
                 _card("re", m["re"], "-", lang)]
    elif r["kind"] == "flow3d":
        cards = [_card("flow_rate", m["flow_rate_m3s"] * 6e4, "L/min", lang), _card("dp", m["dp_pa"], "Pa", lang),
                 _card("max_speed", m["max_speed"], "m/s", lang), _card("re", m["re"], "-", lang)]
    elif r["kind"] == "conjugate":
        cards = [_card("t_solid_max", units.from_si(m["t_solid_max_k"], "degC"), "°C", lang),
                 _card("t_outlet", units.from_si(m["t_outlet_k"], "degC"), "°C", lang),
                 _card("q_in", m["q_in_w"], "W", lang), _card("q_water", m["q_water_w"], "W", lang)]
    elif r["kind"] == "thermal":
        cards = [_card("t_max", units.from_si(m["t_max_k"], "degC"), "°C", lang),
                 _card("t_min", units.from_si(m["t_min_k"], "degC"), "°C", lang)]
        if "q_in_w" in m:
            cards.append(_card("q_in", m["q_in_w"], "W", lang))
    elif r["kind"] == "channel_of":
        cards = [_card("re", m["re"], "-", lang), _card("umax_outlet", m["umax_outlet"], "m/s", lang),
                 _card("max_speed", m["max_speed"], "m/s", lang)]
    cards += [_card("nodes", m.get("nodes", 0), "-", lang, 8), _card("elements", m.get("elements", 0), "-", lang, 8)]

    ref = r.get("reference") or {}
    verification = None
    if ref.get("applicable"):
        scale, unit = (1e3, "mm") if ref["unit"] == "m" else (1.0, ref["unit"])
        conv_ref = ref.get("kind") == "convergence"
        label = t("verify.convergence", lang, q=t(f"qty.study.{ref['quantity']}", lang)) if conv_ref \
            else t(f"verify.{case['template']}", lang)
        verification = {"label": label, "kind": "convergence" if conv_ref else "reference",
                        "reference": ref["reference"] * scale,
                        "computed": ref["computed"] * scale, "unit": unit, "error_pct": ref["error_pct"],
                        "tolerance_pct": ref["tolerance_pct"], "pass": bool(ref["pass"]),
                        "metric": ref.get("metric", "relative error"),
                        "reference_label": t("verify.ref." + ("extrapolated" if conv_ref else
                                                               "analytic" if case["reference"]["kind"] == "analytic"
                                                               else "correlation" if case["reference"]["kind"] == "correlation"
                                                               else "literature"), lang)}
    gates = {"ran": bool(r.get("ran")), "converged": bool(r.get("ran") and r.get("converged")),
             "verified": bool(r.get("ran") and r.get("converged") and verification and verification["pass"])}
    gates_detail = {"converged": r.get("converged_detail"),
                    "verified": None if verification else t(
                        "verify.none_reason" if case["reference"].get("kind") in (None, "none") else "verify.pattern_reason", lang),
                    "verified_detail": None if verification else ref.get("why")}
    quantities = [{"id": q, "label": t(f"qty.{q}", lang), "unit": u, "kind": k} for q, u, k in QUANTITIES[r["kind"]]]
    warnings = []
    sy = (case["materials"].get("solid") or {}).get("sy")
    if r["kind"] == "structural" and sy and m.get("max_vm_pa") and not case.get("body_materials"):
        sy_pa = units.to_si(sy)
        if m["max_vm_pa"] > sy_pa:
            warnings.append({"code": "yield", "message": t("result.yield", lang, vm=m["max_vm_pa"] / 1e6, sy=sy_pa / 1e6)})
    if r["kind"] == "structural" and m.get("peak_on_support") and m.get("max_vm_away_pa"):
        warnings.append({"code": "peak_on_support",
                         "message": t("result.peak_on_support", lang, vm=m["max_vm_pa"] / 1e6, away=m["max_vm_away_pa"] / 1e6)})
    wm = m.get("wall_mesh") or {}
    if r["kind"] == "flow3d" and wm.get("yplus_avg") is not None and not 20 <= wm["yplus_avg"] <= 300:
        warnings.append({"code": "yplus", "message": t("result.yplus", lang, yp=wm["yplus_avg"])})
    if (r.get("convergence") or {}).get("refined") is False:
        n = [l["elements"] for l in r["convergence"]["levels"]]
        warnings.append({"code": "not_refined", "message": t("result.not_refined", lang, a=n[0], b=n[1], c=n[2])})
    ps = (r.get("convergence") or {}).get("peak_stress") or {}
    if ps.get("singular"):
        a, b, c = (v / 1e6 for v in ps["levels_pa"])
        warnings.append({"code": "stress_singular", "message": t("result.stress_singular", lang, a=a, b=b, c=c)})
    return {"run_id": jd.name, "warnings": warnings, "engine": r["engine"], "mode": r["mode"], "revision": r.get("revision"),
            "stale": r.get("revision") != case["revision"], "wall_s": r.get("wall_s"),
            "gates": gates, "gates_detail": gates_detail, "cards": cards, "verification": verification,
            "quantities": quantities, "nova_tool": _nova_tool(case), "convergence": _conv_view(r.get("convergence"), lang)}


def _conv_view(c, lang):
    """Mesh study table for the UI: value per level in display units, GCI and observed order."""
    if not c:
        return None
    scale, unit = (1e3, "mm") if c["unit"] == "m" else (1.0, c["unit"])
    return {"quantity": c["quantity"], "label": t(f"qty.study.{c['quantity']}", lang), "unit": unit,
            "levels": [{"size": l["size"], "elements": l["elements"], "value": l["value"] * scale} for l in c["levels"]],
            "extrapolated": c["f_ext"] * scale if c.get("f_ext") is not None else None, "gci_pct": c["gci_pct"],
            "observed_order": c["p"], "asymptotic": c.get("asymptotic", True),
            "monotone": c["monotone"], "rel_change_pct": c["rel_change_pct"], "tolerance_pct": c["tolerance_pct"],
            "pass": c["pass"]}


def _nova_tool(case):
    from .templates import get
    return get(case["template"]).get("nova_tool")


# ---------------------------------------------------------------- fields for the viewer

def _surface_from_mesh(mesh) -> tuple[np.ndarray, np.ndarray]:
    tris = []
    for k in [f for f in mesh.files if f.startswith("face_")]:
        c = mesh[k]
        if c.shape[1] == 6:
            a, b, cc, ab, bc, ca = c.T
            tris.append(np.stack([np.stack([a, ab, ca], 1), np.stack([ab, b, bc], 1),
                                  np.stack([ca, bc, cc], 1), np.stack([ab, bc, ca], 1)], 1).reshape(-1, 3))
        else:
            tris.append(c[:, :3])
    return np.concatenate(tris)


def _grid_surface(nx, ny, X, Y, z):
    P = np.stack([X.ravel(), Y.ravel(), np.full(X.size, z)], 1)
    idx = np.arange(nx * ny).reshape(ny, nx)
    a, b, c, d = idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel(), idx[1:, 1:].ravel(), idx[1:, :-1].ravel()
    return P, np.concatenate([np.stack([a, b, c], 1), np.stack([a, c, d], 1)])


def field(case: dict, quantity: str, lang: str, run_id: str | None = None) -> dict:
    jd, r = load(case["case_id"], run_id)
    data = np.load(jd / "results.npz")
    kind = r["kind"]
    disp = None
    if kind == "external" and "snappy" in data.files:
        if quantity == "p" and "body_P" in data.files:
            P, idx, s = data["body_P"], data["body_T"], data["body_p"]
        else:
            quantity = "speed"
            P, idx = data["plane_P"], data["plane_T"]
            s = np.linalg.norm(data["plane_U"], axis=1)
            b0, b1 = (np.array(x, float) for x in case["geometry"]["bbox"])
            L = float((b1 - b0).max())
            from .flow3d import DIRS
            dvec = np.abs(np.array(DIRS[case["flow"]["direction"]], float))
            lo, hi = b0 - 2.0 * L, b1 + np.where(dvec > 0, 5.0, 2.0) * L
            cen = P[idx].mean(axis=1)
            idx = idx[np.all((cen >= lo) & (cen <= hi), axis=1)]
        vals = {quantity: s}
    elif kind in ("flow3d", "external"):
        mesh = np.load(jd / "mesh.npz")
        if quantity == "p":
            tri = mesh["face_body"] if kind == "external" else _surface_from_mesh(mesh)
            tri = tri[:, :3]
            used, inv = np.unique(tri, return_inverse=True)
            P = mesh["nodes"][used]
            vals = {"p": data["p"][used]}
            idx = inv.reshape(-1, 3)
        else:
            from .flow3d import slice_plane
            nodes = mesh["nodes"]
            ext = np.ptp(nodes, axis=0)
            normal = np.zeros(3)
            if kind == "external":                                      # plane through the body, containing the flow
                from .flow3d import DIRS
                fa = int(np.argmax(np.abs(DIRS[case["flow"]["direction"]])))
                normal[2 if fa != 2 else 1] = 1.0
                bn = mesh["face_body"][:, :3]
                origin = mesh["nodes"][np.unique(bn)].mean(axis=0)
            else:
                normal[int(np.argmin(ext))] = 1.0                       # cut across the thinnest direction
                origin = nodes.min(axis=0) + ext / 2
            speed = np.linalg.norm(data["U"], axis=1)
            P, idx, s = slice_plane(nodes, mesh["tets"][:, :4], speed, origin, normal)
            if kind == "external" and len(idx):                          # keep the region around the body
                bnodes = mesh["nodes"][np.unique(mesh["face_body"][:, :3])]
                L = float(np.ptp(bnodes, axis=0).max())
                lo, hi = bnodes.min(axis=0) - 2.0 * L, bnodes.max(axis=0) + np.where(
                    np.abs(DIRS[case["flow"]["direction"]]) > 0, 5.0, 2.0) * L
                cen = P[idx].mean(axis=1)
                keep = np.all((cen >= lo) & (cen <= hi), axis=1)
                idx = idx[keep]
            vals = {"speed": s}
    elif kind == "conjugate" and quantity == "speed":
        from .flow3d import slice_plane
        mesh = np.load(jd / "mesh.npz")
        nodes, tets = mesh["nodes"], mesh["tets"][:, :4]
        fluid = [int(k[1:]) for k, i in case["bodies"].items() if i["role"] == "fluid"]
        ft = tets[np.isin(mesh["tet_body"], fluid)]
        fn = nodes[np.unique(ft)]
        ext = np.ptp(fn, axis=0)
        normal = np.zeros(3); normal[int(np.argsort(ext)[1])] = 1.0       # plane along the channel
        P, idx, s = slice_plane(nodes, ft, np.linalg.norm(data["U"], axis=1), fn.mean(axis=0), normal)
        vals = {"speed": s}
    elif kind in ("thermal", "conjugate"):
        mesh = np.load(jd / "mesh.npz")
        tri = _surface_from_mesh(mesh)
        used, inv = np.unique(tri, return_inverse=True)
        P = mesh["nodes"][used]
        vals = {"temp": data["T"][used] - 273.15}
        idx = inv.reshape(-1, 3)
    elif kind == "structural":
        mesh = np.load(jd / "mesh.npz")
        tri = _surface_from_mesh(mesh)
        used, inv = np.unique(tri, return_inverse=True)
        P = mesh["nodes"][used]
        U = data["u"][used]
        vals = {"disp": np.linalg.norm(U, axis=1) * 1e3, "vm": data["vm"][used] / 1e6, "uz": U[:, 2] * 1e3}
        disp = U
        idx = inv.reshape(-1, 3)
    elif kind == "cavity":
        L, Ul = float(data["L"]), float(data["U"])
        x = data["x"] * L
        X, Y = np.meshgrid(x, x)
        zt = geometry.dims(case)[2]
        P, idx = _grid_surface(len(x), len(x), X, Y, zt * 1.001)
        u, v = data["u"] * Ul, data["v"] * Ul
        vals = {"speed": np.hypot(u, v).ravel(), "ux": u.ravel(), "psi": (data["psi"] * Ul * L).ravel()}
    else:  # OpenFOAM cell-centred results on a structured block
        Uc = data["cells"]
        ny, nx, _ = Uc.shape
        Lx = float(data["L"]) if kind == "cavity_of" else float(data["Lx"])
        Ly = float(data["L"]) if kind == "cavity_of" else float(data["g"])
        X, Y = np.meshgrid((np.arange(nx) + 0.5) / nx * Lx, (np.arange(ny) + 0.5) / ny * Ly)
        zt = geometry.dims(case)[2]
        P, idx = _grid_surface(nx, ny, X, Y, zt * 1.001)
        vals = {"speed": np.linalg.norm(Uc, axis=2).ravel(), "ux": Uc[:, :, 0].ravel()}
    if quantity not in vals:
        quantity = next(iter(vals))
    s = vals[quantity]
    unit = dict((q, u) for q, u, _ in QUANTITIES[kind])[quantity]
    out = {"quantity": quantity, "label": t(f"qty.{quantity}", lang), "unit": unit,
           "positions": P.ravel().round(9).tolist(), "indices": idx.ravel().astype(int).tolist(),
           "scalars": np.asarray(s, float).round(9).tolist(), "range": [float(np.min(s)), float(np.max(s))]}
    if disp is not None:
        out["displacement"] = disp.ravel().round(12).tolist()
        bbox = float(np.ptp(P, axis=0).max())
        dmax = float(np.linalg.norm(disp, axis=1).max())
        out["auto_deform_scale"] = float(0.08 * bbox / dmax) if dmax > 0 else 1.0
    return out


# ---------------------------------------------------------------- PNG for the AI (and reports)

def render_png(case: dict, quantity: str, lang: str, run_id: str | None = None) -> tuple[bytes, dict]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    prefs = {"zh": ("Microsoft YaHei", "SimHei", "Noto Sans CJK SC"),
             "ja": ("Yu Gothic", "Meiryo", "MS Gothic", "Noto Sans CJK JP")}.get(lang_of(lang), ("Segoe UI", "Arial"))
    names = {f.name for f in font_manager.fontManager.ttflist}
    for fam in prefs:
        if fam in names:
            plt.rcParams["font.family"] = fam
            break
    from matplotlib import cm, colors
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    f = field(case, quantity, lang, run_id)
    P = np.array(f["positions"]).reshape(-1, 3)
    tri = np.array(f["indices"]).reshape(-1, 3)
    s = np.array(f["scalars"])
    lo, hi = f["range"]
    diverging = f["quantity"] not in ("disp", "vm", "speed", "temp", "p") or \
        (f["quantity"] == "p" and lo < -0.1 * abs(hi))          # suction and stagnation: show the sign
    if diverging:
        m = max(abs(lo), abs(hi), 1e-30)
        lo, hi = -m, m
    cmap = plt.get_cmap("coolwarm" if diverging else "viridis")
    norm = colors.Normalize(lo, hi if hi > lo else lo + 1e-30)
    sm = cm.ScalarMappable(norm=norm, cmap=cmap)
    title = case["title"].get(lang_of(lang), case["title"]["en"])
    ext = np.ptp(P, axis=0)
    is3d = "displacement" in f or ext.min() > 1e-3 * max(ext.max(), 1e-30)     # flat surfaces (slices, 2D) -> 2D plot
    if is3d:
        if "displacement" in f:
            D = np.array(f["displacement"]).reshape(-1, 3)
            Q = P + D * f["auto_deform_scale"]
        else:
            Q = P
        fig = plt.figure(figsize=(8.6, 4.2), dpi=110)
        ax = fig.add_axes([0.0, 0.0, 0.84, 0.9], projection="3d")
        poly = Poly3DCollection(Q[tri], facecolors=cmap(norm(s[tri].mean(axis=1))), edgecolors="none")
        ax.add_collection3d(poly)
        mn, mx = Q.min(axis=0), Q.max(axis=0)
        span = np.maximum(mx - mn, 0.18 * (mx - mn).max())      # keep thin parts visible
        ctr = (mn + mx) / 2
        for setlim, c, sp_ in zip((ax.set_xlim, ax.set_ylim, ax.set_zlim), ctr, span):
            setlim(c - sp_ / 2, c + sp_ / 2)
        ax.set_box_aspect(tuple(span / span.max()), zoom=1.45)
        ax.view_init(20, -62)
        ax.set_axis_off()
        cax = fig.add_axes([0.86, 0.15, 0.02, 0.65])
        note = f" / deformation x{f['auto_deform_scale']:.0f}" if "displacement" in f else ""
    else:
        Lx, Ly = np.ptp(P[:, 0]), np.ptp(P[:, 1])
        aspect = Lx / max(Ly, 1e-12)
        w = 7.6 if aspect < 1.6 else 10.0
        h = max(2.6, min(6.2, w / aspect * 0.86 + 0.9))
        fig = plt.figure(figsize=(w, h), dpi=110)
        ax = fig.add_axes([0.09, 0.12, 0.74, 0.76])
        a0, a1 = sorted(int(a) for a in np.argsort(np.ptp(P, axis=0))[::-1][:2])   # the two in-plane axes
        ax.tripcolor(P[:, a0], P[:, a1], tri, s, cmap=cmap, norm=norm, shading="gouraud")
        if case["template"] == "cavity" and f["quantity"] != "psi":
            jd, r = load(case["case_id"], run_id)
            if r["kind"] == "cavity":
                d = np.load(jd / "results.npz")
                x = d["x"] * float(d["L"])
                ax.streamplot(x, x, d["u"], d["v"], color=(1, 1, 1, 0.55), density=1.1, linewidth=0.6, arrowsize=0.6)
        ax.set_aspect("equal")
        ax.set_xlim(P[:, a0].min(), P[:, a0].max()); ax.set_ylim(P[:, a1].min(), P[:, a1].max())
        ax.set_xlabel("xyz"[a0] + " [m]"); ax.set_ylabel("xyz"[a1] + " [m]")
        cax = fig.add_axes([0.86, 0.12, 0.02, 0.76])
        note = ""
    cb = fig.colorbar(sm, cax=cax)
    cb.set_label(f"{f['label']} [{f['unit']}]")
    fig.suptitle(f"{title} - {f['label']}   min {f['range'][0]:.4g} / max {f['range'][1]:.4g} {f['unit']}{note}",
                 fontsize=10, x=0.02, ha="left", y=0.98)
    fig.text(0.995, 0.01, "NovaSolver Studio · novasolver.jp/studio", ha="right", va="bottom", fontsize=7.5, color="0.45")
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue(), {"quantity": f["quantity"], "unit": f["unit"], "range": f["range"]}