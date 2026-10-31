"""Results: gates, number cards, verification line, viewer fields and PNG renders.
Raw numbers come from <run>/results.json and results.npz written by the worker; this module only presents them."""
from __future__ import annotations

import io
import json
import re
from pathlib import Path

import numpy as np

from . import geometry, units
from .i18n import lang_of, t
from .store import StudioError, case_dir

QUANTITIES = {
    'modal': [('mode', '-', 'sequential')],
    'buckling': [('mode', '-', 'sequential')],
    "electrostatic": [("v", "V", "sequential"), ("emag", "kV/mm", "sequential")],
    "current": [("temp", "°C", "sequential"), ("v", "V", "sequential"), ("jmag", "A/mm2", "sequential"), ("q", "W/cm3", "sequential")],
    "structural": [("vm", "MPa", "sequential"), ("disp", "mm", "sequential"), ("uz", "mm", "diverging")],   # stress first: what decides failure
    "thermal": [("temp", "°C", "sequential")],
    "conjugate": [("temp", "°C", "sequential"), ("speed", "m/s", "sequential")],
    "flow3d": [("speed", "m/s", "sequential"), ("p", "Pa", "sequential")],
    "external": [("speed", "m/s", "sequential"), ("p", "Pa", "diverging")],
    "cavity": [("speed", "m/s", "sequential"), ("ux", "m/s", "diverging"), ("psi", "m2/s", "diverging")],
    "cavity_of": [("speed", "m/s", "sequential"), ("ux", "m/s", "diverging")],
    "channel_of": [("speed", "m/s", "sequential"), ("ux", "m/s", "diverging")],
}


RUN_ID = re.compile(r"^r_\d{8}_\d{6}_[0-9a-f]{4}$")


def latest_done_run(case_id: str, run_id: str | None = None) -> Path | None:
    rd = case_dir(case_id) / "run"
    if not rd.is_dir():
        return None
    if run_id and not RUN_ID.match(run_id):
        # only an id this case generated; "../../other_case/run/..." would show another case's verified result here
        raise StudioError("err.path", 400, path=f"run_id={run_id}")
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


# External-flow section shown around the body, in body lengths: upstream and sideways, and downstream for the wake.
# 2 / 5 lengths made a 24 m airship a small dot in the middle of the view; the full domain stays in the run files.
SECTION_AROUND, SECTION_WAKE = 0.75, 2.5


def _compact(P, idx, values):
    """Keep only the vertices the kept triangles use. Dropping triangles alone left the whole wind tunnel in the
    vertex list, so the viewer framed the tunnel and the body was a dot (and the payload carried it too)."""
    used, inv = np.unique(idx, return_inverse=True)
    return P[used], inv.reshape(idx.shape), np.asarray(values)[used]


def _card(key, value, unit, lang, digits=4):
    return {"key": key, "label": t(f"card.{key}", lang), "value": float(f"{value:.{digits}g}"), "unit": unit}


def display_scale(unit, value):
    if unit == 'Pa':
        return (1e-6,'MPa') if abs(value)>=1e6 else (1e-3,'kPa') if abs(value)>=1e3 else (1,'Pa')
    if unit == "F":
        return (1e12, "pF") if abs(value) < 1e-9 else (1e9, "nF") if abs(value) < 1e-6 else (1e6, "uF")
    if unit == "ohm":
        return (1e3, "mohm") if abs(value) < 1 else (1, "ohm")
    return (1e3, "mm") if unit == "m" else (1, unit)


def quantities_for(r):
    choices = QUANTITIES[r['kind']]
    if r['kind'] == 'structural' and 't_max_k' in r['metrics']:
        choices = choices + [('temp', '°C', 'sequential')]
    if r.get('interfaces'):
        choices = choices + [('p_contact','MPa','sequential'),('contact_gap','mm','sequential'),('contact_slip','mm','sequential'),('contact_status','-','sequential')]
    if r.get('curve'):
        choices = choices + [('peeq','-','sequential')]
    if 'fatigue_sf_min' in r.get('metrics', {}):
        choices = choices + [('fatigue_sf','-','sequential'),('fatigue_life','log10','sequential')]
    return [(q, u, k) for q, u, k in choices
            if not (r["kind"] == "current" and q == "temp" and "t_max_k" not in r["metrics"])]


def payload(case: dict, lang: str, run_id: str | None = None) -> dict:
    jd, r = load(case["case_id"], run_id)
    m = r["metrics"]
    cards = []
    if r['kind'] == 'modal':
        cards = [_card('frequency', m['frequency_hz'], 'Hz', lang)]
    elif r['kind'] == 'buckling':
        cards = [_card('critical_load', m['critical_load_n'], 'N', lang), _card('load_factor', m['load_factor'], '-', lang),
                 _card('applied_load', m['applied_n'], 'N', lang)]
    elif r["kind"] == "electrostatic":
        if "capacitance_f" in m:
            scale, unit = display_scale("F", m["capacitance_f"])
            cards.append(_card("capacitance", m["capacitance_f"] * scale, unit, lang))
        cards += [_card("charge", max(abs(v) for v in m["face_charge_c"].values()), "C", lang),
                  _card("energy", m["energy_j"], "J", lang), _card("e_max", m["e_max_v_m"] / 1e6, "kV/mm", lang)]
    elif r["kind"] == "current":
        if "t_rise_k" in m:
            cards.append(_card("t_rise", m["t_rise_k"], "K", lang))
        cards.append(_card("current", m["current_a"], "A", lang))
        if "resistance_ohm" in m:
            scale, unit = display_scale("ohm", m["resistance_ohm"])
            cards.append(_card("resistance", m["resistance_ohm"] * scale, unit, lang))
        cards.append(_card("power", m["power_w"], "W", lang))
        if "t_max_k" in m:
            cards.append(_card("t_max", units.from_si(m["t_max_k"], "degC"), "°C", lang))
        cards.append(_card("j_max", m["j_max_a_m2"] / 1e6, "A/mm2", lang))
    elif r["kind"] == "structural":
        cards = [_card("tip_disp", m["tip_disp_m"] * 1e3, "mm", lang)] if "tip_disp_m" in m else []
        if "kt" in m:
            cards.append(_card("kt", m["kt"], "-", lang))
        if 'fatigue_sf_min' in m:
            # the minimum next to a rigid support is a singularity: lead with the value away from the supports
            sf = m.get('fatigue_sf_min_away', m['fatigue_sf_min']) if m.get('fatigue_on_support') else m['fatigue_sf_min']
            cards.append(_card('fatigue_sf', min(sf, 1e6), '-', lang, 3))
            cards.append(_card('fatigue_life', min(m['fatigue_life_min'], m['fatigue_infinite']), 'cycles', lang, 3))
        cards += [_card("max_vm", m["max_vm_pa"] / 1e6, "MPa", lang), _card("max_disp", m["max_disp_m"] * 1e3, "mm", lang)]
        if "reaction_n" in m and m.get('applied_n',m['reaction_n']) > max(1e-9,1e-9*m.get('force_scale_n',0)):
            cards.append(_card("reaction", m["reaction_n"], "N", lang))
        elif r.get('interfaces') and 'contact_force_n' not in m:
            force = max(v['normal_force_n'] for v in r['interfaces'].values())
            cards.append(_card('contact_force',force,'N',lang))
        for key, prop, scale, unit in [('thermal_stress','thermal_stress_pa',1e-6,'MPa'),
                ('elongation','elongation_m',1e3,'mm'), ('center_stress','center_stress_pa',1e-6,'MPa'),
                ('twist','twist_rad',1,'rad'), ('shear','shear_pa',1e-6,'MPa')]:
            if prop in m:
                cards.insert(0, _card(key,m[prop]*scale,unit,lang))
        for key,prop,scale,unit in [('contact_pressure','contact_pressure_pa',1e-6,'MPa'),('contact_force','contact_force_n',1,'N'),
                ('contact_shear','contact_shear_n',1,'N'),('axial_stress','axial_stress_pa',1e-6,'MPa'),('limit_load','limit_load_n',1,'N')]:
            if prop in m:
                cards.insert(0,_card(key,m[prop]*scale,unit,lang))
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
        scale, unit = display_scale(ref["unit"], ref["computed"])
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
                    "verified_detail": None if verification else t(ref["why_key"], lang, **ref.get('why_args', {})) if ref.get("why_key") else ref.get("why")}
    quantities = [{"id": q, "label": t(f"qty.{q}", lang), "unit": u, "kind": k} for q, u, k in quantities_for(r)]
    warnings = []
    # Reaching the limit load is the expected end of a collapse run, not a divergence to warn about twice.
    if r.get('limit_reached'):
        warnings.append({'code':'limit_reached','message':t('result.limit_reached',lang,fraction=r['error']['fraction'])})
    elif r.get('error'):
        warnings.append({'code':'nonlinear_diverged','message':t(r['error']['key'],lang,fraction=r['error']['fraction'])})
    if r['kind'] == 'modal' and any(b['role'] == 'displacement' and any(b.get(k) is not None and units.to_si(b[k]) != 0 for k in ('ux','uy','uz')) for b in case['boundaries'].values()):
        warnings.append({'code':'modal_displacement_ignored','message':t('check.modal_displacement_ignored',lang)})
    if r['kind'] == 'structural' and not r.get('large_deformation') and not r.get('limit_reached') and (m.get('max_strain',0)>.01 or m.get('max_rotation',0)>.0872665):
        warnings.append({'code':'large_deformation','message':t('result.large_deformation',lang)})
    if m.get('fatigue_unavailable'):
        warnings.append({'code':'fatigue_unavailable','message':t('result.fatigue_unavailable',lang)})
    if 'fatigue_sf_min' in m:
        sf = m.get('fatigue_sf_min_away', m['fatigue_sf_min']) if m.get('fatigue_on_support') else m['fatigue_sf_min']
        if sf < 1:
            warnings.append({'code':'fatigue_fail','message':t('result.fatigue_fail',lang,sf=sf)})
        if m['fatigue_life_min'] >= m['fatigue_infinite']:
            warnings.append({'code':'fatigue_infinite','message':t('result.fatigue_infinite',lang)})
        warnings.append({'code':'fatigue_basis','message':t('result.fatigue_basis',lang,se=m['fatigue_se_pa']/1e6,
                         su=m['fatigue_su_pa']/1e6,ka=m['fatigue_ka'],r=m['fatigue_ratio'])})
    if r['kind'] == 'buckling':
        if m['load_factor'] < 1:
            warnings.append({'code':'buckles_below_load','message':t('result.buckles_below_load',lang,f=m['load_factor'])})
        warnings.append({'code':'buckling_imperfection','message':t('result.buckling_imperfection',lang)})
    if r.get('free_free'):
        warnings.append({'code':'free_free', 'message':t('result.free_free',lang)})
    if m.get("air_e_max_v_m", 0) > 3e6:
        warnings.append({"code": "air_breakdown", "message": t("result.air_breakdown", lang, e=m["air_e_max_v_m"] / 1e6)})
    sy = (case["materials"].get("solid") or {}).get("sy")
    if r["kind"] == "structural" and sy and m.get("max_vm_pa") and not case.get("body_materials") and case['materials']['solid'].get('model','linear') != 'elastoplastic':
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
    return {"run_id": jd.name, "kind": r["kind"], "warnings": warnings, "engine": r["engine"], "mode": r["mode"], "revision": r.get("revision"),
            "stale": r.get("revision") != case["revision"], "wall_s": r.get("wall_s"),
            "gates": gates, "gates_detail": gates_detail, "cards": cards, "verification": verification,
            "quantities": quantities, "nova_tool": _nova_tool(case), "convergence": _conv_view(r.get("convergence"), lang),
            'curve':r.get('curve',[]),'interfaces':r.get('interfaces',{}),'large_deformation':r.get('large_deformation',False),
            'error':r.get('error'),
            **({'modes':r['modes'], 'free_free':r.get('free_free',False)} if r['kind'] in ('modal', 'buckling') else {})}


def _conv_view(c, lang):
    """Mesh study table for the UI: value per level in display units, GCI and observed order."""
    if not c:
        return None
    scale, unit = display_scale(c["unit"], c["levels"][-1]["value"])
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


def field(case: dict, quantity: str, lang: str, run_id: str | None = None, mode: int = 1, section: dict | None = None, step: int | None = None) -> dict:
    jd, r = load(case["case_id"], run_id)
    data = np.load(jd / "results.npz")
    if step is not None:
        if not isinstance(step,int) or not 1<=step<=len(r.get('curve',[])):
            raise StudioError('err.path',400,path=f'step={step}')
        data = {k[5:] if k.startswith('step_') else k:(data[k][step-1].copy() if k.startswith('step_') else data[k]) for k in data.files}
        # Keep the same interface as np.load below.
        class Fields(dict):
            @property
            def files(self):
                return list(self)
        data = Fields(data)
    kind = r["kind"]
    if not quantity:
        quantity = quantities_for(r)[0][0]
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
            lo, hi = b0 - SECTION_AROUND * L, b1 + np.where(dvec > 0, SECTION_WAKE, SECTION_AROUND) * L
            cen = P[idx].mean(axis=1)
            idx = idx[np.all((cen >= lo) & (cen <= hi), axis=1)]
            P, idx, s = _compact(P, idx, s)
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
                lo, hi = bnodes.min(axis=0) - SECTION_AROUND * L, bnodes.max(axis=0) + np.where(
                    np.abs(DIRS[case["flow"]["direction"]]) > 0, SECTION_WAKE, SECTION_AROUND) * L
                cen = P[idx].mean(axis=1)
                keep = np.all((cen >= lo) & (cen <= hi), axis=1)
                P, idx, s = _compact(P, idx[keep], s)
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
    elif kind in ("electrostatic", "current"):
        mesh = np.load(jd / "mesh.npz")
        tri = _surface_from_mesh(mesh)
        used, inv = np.unique(tri, return_inverse=True)
        P = mesh["nodes"][used]
        vals = {"v": data["V"][used], "emag": np.linalg.norm(data["E"][used], axis=1) / 1e6}
        if "J" in data.files:
            vals.update(jmag=np.linalg.norm(data["J"][used], axis=1) / 1e6, q=data["q"][used] / 1e6)
        if "T" in data.files:
            vals["temp"] = data["T"][used] - 273.15
        idx = inv.reshape(-1, 3)
    elif kind in ("thermal", "conjugate"):
        mesh = np.load(jd / "mesh.npz")
        tri = _surface_from_mesh(mesh)
        used, inv = np.unique(tri, return_inverse=True)
        P = mesh["nodes"][used]
        vals = {"temp": data["T"][used] - 273.15}
        idx = inv.reshape(-1, 3)
    elif kind in ('structural', 'modal', 'buckling'):
        mesh = np.load(jd / "mesh.npz")
        if quantity in ('p_contact','contact_gap','contact_slip','contact_status'):
            contacts = [mesh[k] for k in mesh.files if k.startswith('contact_master_') or k.startswith('contact_slave_')]
            class Surface(dict):
                @property
                def files(self): return list(self)
            tri = _surface_from_mesh(Surface({'face_'+str(i):v for i,v in enumerate(contacts)}))
        else:
            tri = _surface_from_mesh(mesh)
        used, inv = np.unique(tri, return_inverse=True)
        P = mesh["nodes"][used]
        if kind in ('modal', 'buckling'):
            if not 1 <= mode <= len(data['mode_shapes']):
                raise StudioError('err.path',400,path=f'mode={mode}')
            U = data['mode_shapes'][mode-1,used]
            vals = {'mode':np.linalg.norm(U,axis=1)}
        else:
            U = data["u"][used]
            vals = {"disp": np.linalg.norm(U, axis=1) * 1e3, "vm": data["vm"][used] / 1e6, "uz": U[:, 2] * 1e3}
            for q,scale in [('p_contact',1e-6),('contact_gap',1e3),('contact_slip',1e3),('contact_status',1),('peeq',1)]:
                if q in data.files:
                    vals[q] = data[q][used]*scale
            if 'fatigue_sf' in data.files:
                # colour range: a safety factor above 10 and a life past the infinite-life cap read the same
                vals['fatigue_sf'] = np.minimum(data['fatigue_sf'][used], 10.)
                vals['fatigue_life'] = np.log10(np.maximum(data['fatigue_life'][used], 1.))
            if 'T' in data.files:
                vals['temp'] = data['T'][used]-273.15
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
    unit = dict((q, u) for q, u, _ in quantities_for(r))[quantity]
    if section is not None:
        from .sections import section_field
        P, idx, s, disp = section_field(jd, kind, quantity, mode, P, idx, s, disp, section,step)
    out = {"quantity": quantity, "label": t(f"qty.{quantity}", lang), "unit": unit,
           "positions": P.ravel().round(9).tolist(), "indices": idx.ravel().astype(int).tolist(),
           "scalars": np.asarray(s, float).round(9).tolist(), "range": [float(np.min(s)), float(np.max(s))]}
    if disp is not None:
        out["displacement"] = disp.ravel().round(12).tolist()
        bbox = float(np.ptp(P, axis=0).max())
        dmax = float(np.linalg.norm(disp, axis=1).max())
        out["auto_deform_scale"] = 1. if r.get('large_deformation') else float(0.08 * bbox / dmax) if dmax > 0 else 1.0
    if step is not None:
        out['step'] = step
    if kind in ('modal', 'buckling'):
        out['mode'] = mode
    if section is not None:
        out['section'] = section
    return out


# ---------------------------------------------------------------- PNG for the AI (and reports)

def render_png(case: dict, quantity: str, lang: str, run_id: str | None = None, mode: int = 1,step: int | None = None) -> tuple[bytes, dict]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    prefs = {"zh": ("Microsoft YaHei", "SimHei", "PingFang SC", "Noto Sans CJK SC"),
             "ja": ("Yu Gothic", "Meiryo", "MS Gothic", "Hiragino Sans", "Hiragino Kaku Gothic ProN", "Noto Sans CJK JP")}.get(lang_of(lang), ("Segoe UI", "Arial"))
    names = {f.name for f in font_manager.fontManager.ttflist}
    for fam in prefs:
        if fam in names:
            plt.rcParams["font.family"] = fam
            break
    from matplotlib import cm, colors
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    f = field(case, quantity, lang, run_id, mode,step=step)
    P = np.array(f["positions"]).reshape(-1, 3)
    tri = np.array(f["indices"]).reshape(-1, 3)
    s = np.array(f["scalars"])
    lo, hi = f["range"]
    diverging = f["quantity"] not in ("disp", "vm", "speed", "temp", "p", "v", "emag", "jmag", "q", 'mode') or \
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
        note = f" / deformation x{f['auto_deform_scale']:.3g}" if "displacement" in f else ""
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


def render_faces(case: dict, lang: str, view: str = 'iso', highlight: list[str] | None = None) -> tuple[bytes, dict]:
    """Orthographic surface raster with a depth buffer shared by pixels and face labels."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import colors, font_manager
    from matplotlib.patches import Patch
    views = {'iso': [1, -1.4, .9], 'iso_back': [-1, 1.4, -.9], 'top': [0, 0, 1], 'bottom': [0, 0, -1],
             'front': [0, -1, 0], 'back': [0, 1, 0], 'left': [-1, 0, 0], 'right': [1, 0, 0]}
    if view not in views:
        raise StudioError('err.path', 400, path='view='+view)
    prefs = {'ja': ['Yu Gothic', 'Meiryo', 'Hiragino Sans', 'Hiragino Kaku Gothic ProN', 'Noto Sans CJK JP'], 'zh': ['Microsoft YaHei', 'SimHei', 'PingFang SC', 'Noto Sans CJK SC']}.get(lang, ['Segoe UI', 'Arial'])
    fonts = {f.name for f in font_manager.fontManager.ttflist}
    for font in prefs:
        if font in fonts:
            plt.rcParams['font.family'] = font
            break
    faces = geometry.display(case)['faces']
    triangles, owners = [], []
    for i, f in enumerate(faces):
        xyz = np.asarray(f['positions']).reshape(-1, 3)
        tri = np.asarray(f['indices'], int).reshape(-1, 3)
        triangles.extend(xyz[tri])
        owners.extend([i]*len(tri))
    triangles, owners = np.asarray(triangles), np.asarray(owners)
    direction = np.asarray(views[view], float)
    direction /= np.linalg.norm(direction)
    up = np.array([0., 0., 1.]) if abs(direction[2]) < .99 else np.array([0., 1., 0.])
    right = np.cross(up, direction); right /= np.linalg.norm(right)
    up = np.cross(direction, right)
    basis = np.stack([right, up, direction], axis=1)
    projected = triangles @ basis
    lo = projected[:, :, :2].min(axis=(0, 1)); hi = projected[:, :, :2].max(axis=(0, 1))
    w, h = 900, 600
    scale = min((w-80)/max(hi[0]-lo[0], 1e-30), (h-80)/max(hi[1]-lo[1], 1e-30))
    projected[:, :, :2] = (projected[:, :, :2]-(lo+hi)/2)*scale + [w/2, h/2]
    depth = np.full((h, w), -np.inf)
    ids = np.full((h, w), -1, int)
    image = np.ones((h, w, 3))
    # one colour per role: the picture is for a person to check "which face got what", so two roles must never share
    # a tone (fixed and free were both grey and could not be told apart)
    passive = '#c9ccd1'
    role_colour = {'fixed': '#2563eb', 'symmetry': '#0d9488', 'constraint': '#7c3aed', 'load': '#ea580c',
                   'pressure': '#dc2626', 'temperature': '#9333ea', 'heat-flux': '#ea580c', 'convection': '#38bdf8',
                   'voltage': '#9333ea', 'surface-charge': '#ea580c', 'current': '#ea580c', 'inlet': '#16a34a',
                   'outlet': '#d97706', 'moving-wall': '#ea580c', 'water-inlet': '#16a34a', 'water-outlet': '#d97706'}
    interfaces = {f['key'] for f in case['geometry'].get('faces',[]) if f.get('interface')}
    role_colour['contact'] = role_colour['inlet']
    roles = ['contact' if f['key'] in interfaces else case['boundaries'].get(f['key'], {}).get('role') for f in faces]
    palette = {r: role_colour.get(r, passive) for r in roles if r}
    palette[None] = '#f59e0b'                                 # no role at all: should not happen, make it stand out
    groups = roles
    for p, world, owner in zip(projected, triangles, owners):
        a, b, c = p
        xmin, ymin = np.maximum(np.floor(p[:, :2].min(0)).astype(int), 0)
        xmax, ymax = np.minimum(np.ceil(p[:, :2].max(0)).astype(int), [w-1, h-1])
        if xmin > xmax or ymin > ymax:
            continue
        denom = (b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(denom) < 1e-12:
            continue
        yy, xx = np.mgrid[ymin:ymax+1, xmin:xmax+1]
        u = ((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/denom
        v = ((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/denom
        z = u*a[2]+v*b[2]+(1-u-v)*c[2]
        dest = depth[ymin:ymax+1, xmin:xmax+1]
        mask = (u >= -1e-8) & (v >= -1e-8) & (u+v <= 1+1e-8) & (z > dest)
        dest[mask] = z[mask]
        ids[ymin:ymax+1, xmin:xmax+1][mask] = owner
        color = ('#0891b2' if faces[owner]['key'] in highlight else passive) if highlight is not None else palette[groups[owner]]
        normal = np.cross(world[1]-world[0], world[2]-world[0])
        shade = .72+.28*abs(normal @ direction)/max(np.linalg.norm(normal), 1e-30)
        image[ymin:ymax+1, xmin:xmax+1][mask] = np.asarray(colors.to_rgb(color))*shade
    # face borders: a pixel whose neighbour belongs to another face (or to the background) is an edge
    edge = np.zeros((h, w), bool)
    edge[:, 1:] |= ids[:, 1:] != ids[:, :-1]
    edge[1:, :] |= ids[1:, :] != ids[:-1, :]
    near = np.zeros_like(edge)
    near[:, :-1] |= edge[:, 1:]
    near[:-1, :] |= edge[1:, :]
    image[(edge | near) & ((ids >= 0) | np.roll(ids >= 0, 1, 0) | np.roll(ids >= 0, 1, 1))] = colors.to_rgb('#30343a')
    # crop to the part with a margin, so the part fills the picture
    ys, xs = np.nonzero(ids >= 0)
    if len(xs):
        x0, x1 = max(xs.min() - 30, 0), min(xs.max() + 30, w - 1)
        y0, y1 = max(ys.min() - 30, 0), min(ys.max() + 30, h - 1)
    else:
        x0, x1, y0, y1 = 0, w - 1, 0, h - 1
    fig, ax = plt.subplots(figsize=(9, 6.7), dpi=110)
    ax.imshow(image, origin='lower'); ax.set_axis_off()
    ax.set_xlim(x0, x1); ax.set_ylim(y0, y1)
    labelled = []
    for i, f in enumerate(faces):
        candidates = projected[owners == i].mean(axis=1)
        center = candidates.mean(0)
        for p in sorted(candidates, key=lambda p: np.linalg.norm(p[:2]-center[:2])):
            x, y = np.rint(p[:2]).astype(int)
            if 0 <= x < w and 0 <= y < h and ids[y, x] == i:
                n = next((g['n'] for g in case['geometry'].get('faces', []) if g['key'] == f['key']), i+1)
                ax.text(x, y, str(n), ha='center', va='center', fontsize=10,
                        bbox=dict(boxstyle='round,pad=.2', fc='white', ec='0.4', lw=.5))
                labelled.append(f['key'])
                break
    legend = [Patch(facecolor=palette[r], edgecolor='#30343a', label=t('role.'+r, lang)) for r in dict.fromkeys(roles) if r]
    if highlight is not None:
        legend = [Patch(facecolor='#0891b2', label=t('render.highlight', lang))]
    fig.legend(handles=legend, loc='lower center', ncol=min(5, max(1, len(legend))), frameon=False)
    ax.set_title(t('render.faces', lang))
    buf = io.BytesIO()
    fig.savefig(buf, format='png'); plt.close(fig)
    return buf.getvalue(), {'quantity': 'faces', 'view': view, 'labelled_faces': labelled, 'highlight': highlight}
