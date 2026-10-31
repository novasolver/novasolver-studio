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
    if any(c.get('type','bonded') != 'bonded' for c in case.get('contacts',{}).values()):
        from .contact import split_mesh
        import hashlib
        key = hashlib.sha256(('contact-v3'+geometry.mesh_key(case)+json.dumps(case.get('contacts',{}),sort_keys=True)).encode()).hexdigest()[:16]
        cache = geometry.mesh_dir(case)/('contact_'+key+'.npz')
        record = cache.with_suffix('.json')
        if cache.is_file() and record.is_file():
            m = dict(np.load(cache))
            pairs = json.loads(record.read_text(encoding='utf-8'))
            for r in pairs:
                for k in ('master','slave','normal','area','pressure_tri','pressure_mass'):
                    if k in r:
                        r[k] = np.asarray(r[k],int if k in ('master','slave','pressure_tri') else float)
        else:
            m,pairs = split_mesh(case,m)
            np.savez_compressed(cache,**m)
            _write_json(record,[{k:v.tolist() if isinstance(v,np.ndarray) else v for k,v in r.items()} for r in pairs])
        np.savez_compressed(jd/'mesh.npz',**m)
        m['_contact_pairs'] = pairs
    if case.get('contact_pairs'):
        from .contact import mortar_pairs
        from .store import StudioError
        prog('job.contact_search', 0.06)
        records = mortar_pairs(case, m)
        missing = [r for r in records if r.get('no_contact')]
        if missing:
            r = missing[0]
            raise StudioError('err.contact_pair_none', 400, pair=r['face'],
                              distance='-' if r['closest_m'] is None else f"{r['closest_m']*1e3:.3g}")
        m['_contact_pairs'] = list(m.get('_contact_pairs', [])) + records
    return m


PASSIVE_ROLES = {None, "free", "insulated", "wall", "open"}   # the default role of each physics: no condition to lose


def check_condition_faces(case: dict, m: dict) -> None:
    """Every face that carries a condition must be in the mesh. Otherwise the solver would quietly run without that
    support or load and report a converged but meaningless answer (seen when a remesh lost a face's name)."""
    from .store import StudioError
    lost = sorted(k for k, b in case.get("boundaries", {}).items()
                  if (b.get("role") not in PASSIVE_ROLES or
                      (case.get("physics", {}).get("joule_heating", True) and b.get("thermal", {}).get("role", "insulated") not in PASSIVE_ROLES))
                  and len(m.get(f"face_{k}", ())) == 0)
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
        if b['role'] in ('moment', 'bearing', 'remote-force'):
            from .structural import face_load
            tractions.append((tri, face_load(case, face, nodes, tri, b)))
            continue
        area = tri_areas(nodes, tri)
        if b["role"] == "load":
            F = units.to_si(b["force"])
            d = b.get("direction", "-z")
            if d == "normal":
                vec = -outward_normals(nodes, tets, tri)            # pushes into the face
            else:
                from .structural import direction
                vec = np.broadcast_to(direction(d), (len(tri), 3))
            tractions.append((tri, vec * F / area.sum()))
        elif b["role"] == "pressure":
            from .structural import pressure_load
            tractions.append((tri, pressure_load(nodes, tets, tri, units.to_si(b["pressure"]))))
    return fixed, tractions


def symmetry_rollers(case: dict, m: dict) -> list[tuple[np.ndarray, int]]:
    """Symmetry faces: flat and normal to x, y or z; the displacement along that axis is zero there.
    Without a fixed face, the symmetry planes must cover all three axes or the part can still slide or spin."""
    from .store import StudioError
    out = []
    for face, b in case["boundaries"].items():
        tri = m.get(f"face_{face}")
        if tri is None:
            continue
        if b['role'] == 'beam-clamp':
            nds = np.unique(tri); xyz = m['nodes'][nds]
            span = np.ptp(xyz,axis=0); axis = int(np.argmin(span))
            if span[axis]>max(span.max(),1e-30)*1e-8:
                raise StudioError('err.symmetry_plane',400,face=face)
            a,c = [i for i in range(3) if i != axis]
            center = (xyz.min(0)+xyz.max(0))/2
            middle = nds[np.argmin(np.linalg.norm(xyz-center,axis=1))]
            edge = center.copy(); edge[c] = xyz[:,c].max()
            tip = nds[np.argmin(np.linalg.norm(xyz-edge,axis=1))]
            # Fix section translation/rotation while permitting Poisson contraction and warping.
            out += [(tri,axis),(np.array([[middle]]),a),(np.array([[middle]]),c),(np.array([[tip]]),a)]
            continue
        if b["role"] == "constraint":           # chosen components held on any face (a guide, a slider)
            out += [(tri, "xyz".index(c)) for c in b.get("components", "")]
            continue
        if b["role"] != "symmetry":
            continue
        P = m["nodes"][tri[:, :3]]
        n = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
        n /= np.linalg.norm(n, axis=1, keepdims=True)
        axis = int(np.argmax(np.abs(n).sum(axis=0)))
        if np.abs(n[:, axis]).min() < 0.9999:
            raise StudioError("err.symmetry_plane", 400, face=face)
        out.append((tri, axis))
    if out and case.get('physics', {}).get('analysis') != 'modal' and not any(b["role"] in ('fixed','beam-clamp','displacement','spring') for b in case["boundaries"].values()) and len({a for _, a in out}) < 3:
        raise StudioError("err.symmetry_rbm", 400)
    return out


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
    from .templates import element_prop
    E, nu = element_prop(case, m, "E"), element_prop(case, m, "nu")     # per element for multi-material assemblies
    if case.get('physics', {}).get('analysis') == 'modal':
        return run_modal(case, jd, prog, m)
    if case.get('physics', {}).get('analysis') == 'buckling':
        return run_buckling(case, jd, prog, m)
    if case.get('physics',{}).get('analysis') == 'nonlinear' or m.get('_contact_pairs') or any(
            b['role'] in ('displacement','spring') for b in case['boundaries'].values()):
        return run_incremental(case,jd,prog,m)
    fixed, tractions = structural_loads(case, m)
    from .structural import acceleration, temperatures
    T = temperatures(case, m, lambda k, f: prog(k, f))
    r = fem_tet10.solve(nodes, tets, E, nu, fixed, tractions, progress=lambda k, f: prog(k, f),
                        rollers=symmetry_rollers(case, m), rho=element_prop(case, m, 'rho'), acceleration=acceleration(case),
                        alpha=element_prop(case, m, 'alpha'), temperature=T,
                        T_ref=units.to_si(case['physics'].get('T_ref', {'value': 20, 'unit': 'degC'})))
    U = r["u"]
    umag = np.linalg.norm(U, axis=1)
    extra, fatigue_metrics = fatigue_fields(case, nodes, fixed, r["s"])
    np.savez_compressed(jd / "results.npz", u=U, vm=r["vm"], s=r["s"], reaction=r['nodal_reaction'], **extra,
                        **({'T': fem_tet10.nodal_temperatures(T,nodes,fem_tet10.canonical_tets(nodes,tets))} if T is not None else {}))
    metrics = {"max_vm_pa": float(r["vm"].max()), "max_disp_m": float(umag.max()),
               "reaction_n": float(np.linalg.norm(r["reaction"])), "applied_n": float(np.linalg.norm(r["applied"])),
               "imbalance": r["imbalance"], "nodes": int(len(nodes)), "elements": int(len(tets)),
               'force_scale_n':float(np.linalg.norm(np.abs(r['forces']).sum(0)))}
    metrics.update(max_strain=r['max_strain'],max_rotation=r['max_rotation'])
    metrics.update(applied_force_n=r['applied'].tolist(), reaction_force_n=r['reaction'].tolist(),
                   applied_moment_nm=r['applied_moment'].tolist(), reaction_moment_nm=r['reaction_moment'].tolist())
    if T is not None:
        metrics.update(t_min_k=float(T.min()), t_max_k=float(T.max()))
    metrics.update(support_peak(nodes, fixed, r["vm"]))
    metrics.update(fatigue_metrics)
    if case["template"] == "cantilever":
        metrics["tip_disp_m"] = float(-U[np.unique(m["face_x1"]), 2].mean())
        ref = reference_cantilever(case, metrics["tip_disp_m"])
    elif case["template"] == "plate-hole":
        ref = reference_plate_hole(case, m["nodes"], r["vm"], metrics)
    else:
        from .structural import reference
        ref = reference(case, m, r, metrics)
    converged = bool(r["imbalance"] < 5e-3 and np.isfinite(umag).all())
    return {"kind": "structural", "metrics": metrics, "converged": converged,
            "converged_detail": {"imbalance": r["imbalance"], "limit": 5e-3}, "reference": ref}


def fatigue_fields(case, nodes, fixed, stress):
    """Nodal fatigue safety factor and life when physics.fatigue is on (one metal material). The minimum next to a
    fully fixed face is a singularity like the peak stress there, so the minimum away from the supports is kept too."""
    from .fatigue import settings, material, evaluate, INFINITE
    if not settings(case)['enabled']:
        return {}, {}
    mat = None if case.get('body_materials') else material(case)
    if mat is None:
        return {}, {'fatigue_unavailable': True}
    f = evaluate(stress, case, mat)
    sf = np.where(np.isfinite(f['sf']), f['sf'], 1e6)
    m = {'fatigue_sf_min': float(sf.min()), 'fatigue_life_min': float(f['life'].min()), 'fatigue_infinite': INFINITE,
         'fatigue_se_pa': f['se_pa'], 'fatigue_su_pa': f['su_pa'], 'fatigue_ka': f['ka'], 'fatigue_ratio': f['ratio'],
         'fatigue_at_m': nodes[int(np.argmin(sf))].tolist()}
    away = support_peak(nodes, fixed, -sf)                       # the same "a couple of elements away" rule
    if away.get('max_vm_away_pa') is not None:
        m['fatigue_sf_min_away'] = float(-away['max_vm_away_pa'])
    return {'fatigue_sf': sf, 'fatigue_life': f['life']}, m


def prescribed_displacements(case,m):
    return [(m['face_'+face],i,units.to_si(b[k])) for face,b in case['boundaries'].items()
            if b['role'] == 'displacement' for i,k in enumerate(('ux','uy','uz')) if b.get(k) is not None]


def modal_rollers(case,m):
    return symmetry_rollers(case,m)+[(tri,c) for tri,c,value in prescribed_displacements(case,m) if value == 0]


def spring_stiffness(case,m):
    from .structural import surface_rule
    springs = np.zeros((len(m['nodes']),3))
    for f,b in case['boundaries'].items():
        if b['role'] == 'spring':
            tri = m['face_'+f]; _,w,_ = surface_rule(m['nodes'],tri)
            for j,weight in enumerate((1/12,1/12,1/12,1/4,1/4,1/4)):
                for c in b.get('components','xyz'):
                    np.add.at(springs[:, 'xyz'.index(c)],tri[:,j],units.to_si(b['stiffness'])*w.sum(1)/w.sum()*weight)
    return springs


def run_incremental(case,jd,prog,m):
    from . import fem_nonlinear as nl
    from .templates import element_groups,element_prop
    from .structural import acceleration,temperatures,reference,follower_pressure
    fixed,tractions = structural_loads(case,m)
    physics = case['physics']; nonlinear = physics.get('analysis') == 'nonlinear'
    options = physics.get('nonlinear',{}) if nonlinear else {}
    large = bool(options.get('large_deformation',True)) if nonlinear else False
    if large:
        pressure_tri = [m['face_'+f] for f,b in case['boundaries'].items() if b['role'] == 'pressure']
        tractions = [(tri,t) for tri,t in tractions if not any(tri is p for p in pressure_tri)]
    nodes,tets = m['nodes'],m['tets']
    T = temperatures(case,m,lambda k,f:prog(k,f))
    springs = spring_stiffness(case,m)
    face = options.get('face','x1' if 'face_x1' in m else 'top' if 'face_top' in m else next(iter(case['boundaries']),''))
    r = nl.solve(nodes,tets,element_groups(case,m.get('tet_body',np.zeros(len(tets),int))),fixed,tractions,
        symmetry_rollers(case,m),prescribed_displacements(case,m),large=large,
        steps=options.get('steps','auto') if nonlinear else 1,max_iterations=options.get('max_iterations',25),
        contact_pairs=m.get('_contact_pairs',()),rho=element_prop(case,m,'rho'),acceleration=acceleration(case),
        alpha=element_prop(case,m,'alpha'),temperature=T,T_ref=units.to_si(physics.get('T_ref',{'value':20,'unit':'degC'})),
        follower=follower_pressure(case,m) if large else None,progress=prog,path=options.get('path'),springs=springs,
        face_nodes=np.unique(m.get('face_'+face,np.empty(0,int))))
    fields = {k:v for k,v in r['steps'][-1].items()}
    if nonlinear:
        fields.update({'step_'+k:np.stack([s[k] for s in r['steps']]) for k in fields})
    if T is not None:
        from .fem_tet10 import nodal_temperatures,canonical_tets
        fields['T'] = nodal_temperatures(T,nodes,canonical_tets(nodes,tets))
    np.savez_compressed(jd/'results.npz',**fields)
    metrics = {'max_vm_pa':float(r['vm'].max()),'max_disp_m':float(np.linalg.norm(r['u'],axis=1).max()),
        'reaction_n':float(np.linalg.norm(r['reaction'])),'applied_n':float(np.linalg.norm(r['applied'])),
        'force_scale_n':float(np.linalg.norm(np.abs(r['forces']).sum(0))),
        'imbalance':r['imbalance'],'nodes':len(nodes),'elements':len(tets),'newton_iterations':r['iterations'],
        'complementarity':r['complementarity'],'max_strain':r['max_strain'],
        'applied_force_n':r['applied'].tolist(),'reaction_force_n':r['reaction'].tolist(),
        'applied_moment_nm':r['applied_moment'].tolist(),'reaction_moment_nm':r['reaction_moment'].tolist()}
    metrics.update(support_peak(nodes,fixed,r['vm']))
    if T is not None:
        metrics.update(t_min_k=float(T.min()),t_max_k=float(T.max()))
    ref = reference(case,m,r,metrics)
    return {'kind':'structural','metrics':metrics,'converged':r['converged'],
        'converged_detail':{'imbalance':r['imbalance'],'complementarity':r['complementarity'],
                            'residual_history':r['residual_history'],'error':r['error']},
        'reference':ref,'interfaces':r['interfaces'],'curve':r['curve'] if nonlinear else [],
        'large_deformation':large,'error':r['error'],'limit_reached':r['limit_reached']}


def run_modal(case, jd, prog, m):
    from .fem_tet10 import solve_modal
    from .templates import element_prop
    fixed = [m['face_'+f] for f,b in case['boundaries'].items() if b['role'] == 'fixed']
    r = solve_modal(m['nodes'], m['tets'], element_prop(case,m,'E'), element_prop(case,m,'nu'),
                    element_prop(case,m,'rho'), fixed, modal_rollers(case,m),
                    int(case['physics'].get('modes',6)), lambda k,f: prog(k,f),springs=spring_stiffness(case,m))
    np.savez_compressed(jd/'results.npz', phi=r['phi'], mode_shapes=r['mode_shapes'])
    metrics = {'frequency_hz': r['modes'][0]['frequency_hz'], 'nodes': len(m['nodes']), 'elements': len(m['tets'])}
    from .structural import modal_reference
    return {'kind': 'modal', 'modes': r['modes'], 'free_free': r['free_free'], 'metrics': metrics,
            'converged': r['converged'], 'converged_detail': {'eigen_residual': r['residual'], 'limit': 1e-5},
            'reference': modal_reference(case, r['modes'])}


def run_buckling(case, jd, prog, m):
    from .fem_tet10 import solve_buckling
    from .templates import element_prop
    from .store import StudioError
    fixed, tractions = structural_loads(case, m)
    try:
        r = solve_buckling(m['nodes'], m['tets'], element_prop(case,m,'E'), element_prop(case,m,'nu'), fixed, tractions,
                           symmetry_rollers(case,m), prescribed_displacements(case,m), int(case['physics'].get('modes',4)),
                           lambda k,f: prog(k,f), springs=spring_stiffness(case,m))
    except RuntimeError as e:
        raise StudioError('err.buckling_failed', 400, why=str(e))
    if not r['load_factors']:
        raise StudioError('err.buckling_none', 400)
    p0 = r['applied_load']
    table = [{'mode': i+1, 'load_factor': lam, 'critical_load_n': lam*p0} for i, lam in enumerate(r['load_factors'])]
    np.savez_compressed(jd/'results.npz', u=r['u'], mode_shapes=r['mode_shapes'], phi=r['mode_shapes'])
    metrics = {'load_factor': table[0]['load_factor'], 'critical_load_n': table[0]['critical_load_n'], 'applied_n': p0,
               'nodes': len(m['nodes']), 'elements': len(m['tets']), 'negative_factors': r['negative_factors']}
    from .structural import buckling_reference
    return {'kind': 'buckling', 'modes': table, 'free_free': False, 'metrics': metrics,
            'converged': r['converged'], 'converged_detail': {'eigen_residual': r['residual'], 'limit': 1e-5},
            'reference': buckling_reference(case, table)}


def thermal_groups(case: dict, m: dict, nested=False):
    fixed, fluxes, conv, order = [], [], [], {"fixed": [], "flux": [], "convection": []}
    for face, b in case["boundaries"].items():
        if nested:
            b = b.get("thermal", {"role": "insulated"})
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
    from .templates import element_k
    k = element_k(case, m)
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


EPS0 = 8.8541878128e-12


def run_electric_builtin(case: dict, jd: Path, prog) -> dict:
    from . import fem_tet10 as fem
    from .templates import element_prop, element_groups
    from .store import StudioError
    m = _mesh_for_run(case, jd, prog)
    nodes, tets = m["nodes"], m["tets"]
    current = case["physics"]["kind"] == "dc-current"
    coeff = element_prop(case, m, "sigma" if current else "eps_r") * (1 if current else EPS0)
    fixed, fluxes, names, flux_names, volts = [], [], [], [], {}
    for face, b in case["boundaries"].items():
        tri = m.get(f"face_{face}")
        if tri is None:
            continue
        if b["role"] == "voltage":
            v = units.to_si(b["voltage"])
            fixed.append((tri, v)); names.append(face); volts[face] = v
        elif b["role"] in ("current", "surface-charge"):
            q = units.to_si(b["current"] if current else b["charge"])
            if current:
                q /= fem.tri_areas(nodes, tri).sum()
            fluxes.append((tri, q)); flux_names.append(face)
    if not fixed:
        raise StudioError("err.no_voltage", 400)
    r = fem.solve_scalar(nodes, tets, coeff, fixed, fluxes, [], progress=prog)
    V = r["value"]
    Eg = -r["gradient"]
    # nodal fields are recovered per material: E, J and q jump across a dielectric or conductor interface
    groups = [idx for idx, _ in element_groups(case, m.get("tet_body", np.zeros(len(tets), int)))]
    E = fem.gauss_to_nodes(r["tets"], Eg, len(nodes), groups)
    qg = np.broadcast_to(coeff, len(tets))[:, None] * np.sum(Eg ** 2, axis=2)
    integral = float(np.sum(qg * r["weights"]))
    emag = np.linalg.norm(E, axis=1)
    imax = int(np.argmax(emag))
    flows = {f: v for f, v in zip(names + flux_names, r["flows"]["fixed"] + r["flows"]["flux"])}
    metrics = {"nodes": len(nodes), "elements": len(tets), "imbalance": r["imbalance"],
               "e_max_v_m": float(emag[imax]), "e_max_at_m": nodes[imax].tolist()}
    fields = {"V": V, "E": E}
    levels = sorted(set(volts.values()))
    dv = levels[-1] - levels[0]
    high_flow = sum(flows[f] for f in names if volts[f] == levels[-1])
    # what goes through the part: everything that enters (the same as what leaves), whichever terminal drives it
    through = sum(v for v in flows.values() if v > 0)
    # a prescribed current or charge adds its own share to the electrode reactions: then a ratio of one electrode's
    # charge (or current) to the voltage is not the capacitance (or resistance) of the part
    sourced = any(abs(q) > 0 for _, q in fluxes)
    converged = r["imbalance"] < 1e-3 and np.isfinite(V).all()
    detail = {"electric_balance_error": r["imbalance"], "limit": 1e-3}
    if current:
        J = fem.gauss_to_nodes(r["tets"], np.broadcast_to(coeff, len(tets))[:, None, None] * Eg, len(nodes), groups)
        fields.update(J=J, q=fem.gauss_to_nodes(r["tets"], qg, len(nodes), groups))
        metrics.update(face_current_a=flows, current_a=through, power_w=integral,
                       j_max_a_m2=float(np.linalg.norm(J, axis=1).max()))
        if len(levels) == 2 and not sourced and high_flow != 0:
            metrics["resistance_ohm"] = dv / high_flow
        if case["physics"].get("joule_heating", True):
            tf, tq, tc, order = thermal_groups(case, m, nested=True)
            tr = fem.solve_thermal(nodes, tets, element_prop(case, m, "k"), tf, tq, tc, progress=prog, source=qg)
            T = tr["T"]
            fields["T"] = T
            metrics.update(t_max_k=float(T.max()), t_min_k=float(T.min()), q_joule_w=tr["source_total"],
                           heat_imbalance=tr["imbalance"], q_in_w=tr["total_in"],
                           face_flows_w={f: q for g in order for f, q in zip(order[g], tr["flows"][g])})
            # rise above the coldest thermal reference: a fixed temperature, else the convection ambient (the part
            # warms as a whole above the air; max - min of the part alone would miss that)
            refs = [t for _, t in tf] or [tinf for _, _, tinf in tc]
            metrics["t_rise_k"] = float(T.max() - min(refs)) if refs else float(T.max() - T.min())
            converged = converged and tr["imbalance"] < 1e-3 and np.isfinite(T).all()
            detail["heat_balance_error"] = tr["imbalance"]
    else:
        metrics.update(face_charge_c=flows, energy_j=integral / 2)
        if len(levels) == 2 and not sourced:
            metrics["capacitance_f"] = abs(high_flow) / dv
    air_elements = []
    body_mats = case.get("body_materials", {})
    for idx, _ in element_groups(case, m.get("tet_body", np.zeros(len(tets), int))):
        if not body_mats and case["materials"]["solid"].get("preset") == "air":
            air_elements.append(idx)
    for body, preset in body_mats.items():
        if preset == "air":
            air_elements.append(np.where(m["tet_body"] == int(body[1:]))[0])
    if air_elements:
        nds = np.unique(tets[np.concatenate(air_elements)])
        metrics["air_e_max_v_m"] = float(emag[nds].max())
    ref = reference_electric(case, metrics)
    np.savez_compressed(jd / "results.npz", **fields)
    return {"kind": "current" if current else "electrostatic", "metrics": metrics, "converged": bool(converged),
            "converged_detail": detail, "reference": ref}


def reference_electric(case, metrics):
    from .reference_loads import unsupported_loads
    excluded = unsupported_loads(case)
    if excluded:
        return excluded
    b = case["boundaries"]
    tid = case["template"]
    p = case["geometry"].get("params", {})
    na = {"applicable": False, "why_key": "verify.electric_pattern_reason"}
    if case.get("body_materials") or tid not in ("capacitor", "coax", "busbar"):
        return na
    ends = ("inner", "outer") if tid == "coax" else ("z0", "z1") if tid == "capacitor" else ("x0", "x1")
    if not all(b[f]["role"] == "voltage" for f in ends):
        return na
    passive = "insulated" if tid == "busbar" else "open"
    if not all(v["role"] == passive for f, v in b.items() if f not in ends):
        return na
    dv = abs(units.to_si(b[ends[0]]["voltage"]) - units.to_si(b[ends[1]]["voltage"]))
    if dv == 0:
        return na
    mat = case["materials"]["solid"]
    if tid == "busbar":
        if not case["physics"].get("joule_heating", True):
            return na
        tb = {f: v.get("thermal", {"role": "insulated"}) for f, v in b.items()}
        if not (all(tb[f]["role"] == "temperature" for f in ends) and
                all(v["role"] == "insulated" for f, v in tb.items() if f not in ends)):
            return na
        ts = [units.to_si(tb[f]["temperature"]) for f in ends]
        if abs(ts[0] - ts[1]) > 1e-9:
            return na
        L, w, h = (units.to_si(p[k]) for k in ("length", "width", "height"))
        sigma, k = units.to_si(mat["sigma"]), units.to_si(mat["k"])
        resistance = L / (sigma * w * h)
        metrics.update(resistance_reference_ohm=resistance, current_reference_a=dv / resistance)
        ref, computed, quantity, unit = sigma * dv ** 2 / (8 * k), metrics["t_rise_k"], "t_rise", "K"
        formula = "T_max - T0 = sigma dV^2 / (8 k)"
    else:
        eps = EPS0 * units.to_si(mat["eps_r"])
        if tid == "capacitor":
            L, w, h = (units.to_si(p[k]) for k in ("length", "width", "height"))
            ref = eps * L * w / h
            formula = "C = eps0 eps_r L W / d"
        else:
            a, bb, L = (units.to_si(p[k]) for k in ("a", "b", "length"))
            ref = 2 * math.pi * eps * L / math.log(bb / a)
            metrics["e_max_reference_v_m"] = dv / (a * math.log(bb / a))
            metrics["e_max_error_pct"] = (metrics["e_max_v_m"] / metrics["e_max_reference_v_m"] - 1) * 100
            formula = "C = 2 pi eps0 eps_r L / ln(b/a)"
        computed, quantity, unit = metrics.get("capacitance_f"), "capacitance", "F"
        if computed is None:
            return na
    err = (computed / ref - 1) * 100
    tol = case["reference"]["tolerance_pct"]
    return {"applicable": True, "quantity": quantity, "reference": ref, "computed": computed, "unit": unit,
            "error_pct": err, "tolerance_pct": tol, "pass": abs(err) <= tol, "formula": formula}


def reference_thermal_block(case: dict, face_flows: dict) -> dict:
    from .reference_loads import unsupported_loads
    excluded = unsupported_loads(case)
    if excluded:
        return excluded
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
    from .reference_loads import unsupported_loads
    excluded = unsupported_loads(case)
    if excluded:
        return excluded
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
    from .reference_loads import unsupported_loads
    excluded = unsupported_loads(case)
    if excluded:
        return excluded
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
    from .reference_loads import unsupported_loads
    excluded = unsupported_loads(case)
    if excluded:
        return excluded
    b = case["boundaries"]
    pattern_ok = b["x0"]["role"] == "fixed" and b["x1"]["role"] == "load" and b['x1'].get('direction') == '-z' and \
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
    # the mesh study must track a response of the solution: a prescribed current or charge comes back unchanged on
    # every mesh (conservation), so it would "converge" whatever the accuracy
    if k == "electrostatic":
        if "capacitance_f" in m:
            return ("capacitance", m["capacitance_f"], "F")
        return ("energy", m["energy_j"], "J")
    if k == "current":
        if "t_rise_k" in m:
            return ("t_rise", m["t_rise_k"], "K")
        if "resistance_ohm" in m:
            return ("resistance", m["resistance_ohm"], "ohm")
        return ("power", m["power_w"], "W")
    if k == "structural":
        response = {'press-fit':('contact_pressure','contact_pressure_pa','Pa'),
                    'large-cantilever':('tip_disp','tip_disp_m','m'),
                    'plastic-bar':('axial_stress','axial_stress_pa','Pa'),
                    'plastic-beam-collapse':('limit_load','limit_load_n','N'),
                    'rubber-tension':('axial_stress','axial_stress_pa','Pa'),
                    'hertz-cylinder':('contact_pressure','contact_pressure_pa','Pa'),
                    'fatigue-bar':('fatigue_sf','fatigue_sf_min','-')}.get(case['template'])
        if response and response[1] in m:
            return response[0],m[response[1]],response[2]
        return ("max_disp", m["max_disp_m"], "m")
    if k == 'modal':
        return ('frequency', m['frequency_hz'], 'Hz')
    if k == 'buckling':
        return ('critical_load', m['critical_load_n'], 'N')
    if k == "thermal":
        n_fixed = sum(1 for b in case["boundaries"].values() if b.get("role") == "temperature")
        if n_fixed >= 2:
            # the temperature span is imposed by the two fixed faces: only the heat flow measures the solution
            if m.get("q_in_w") is None:
                raise ValueError("no heat-flow metric for a case with two fixed temperatures")
            return ("q_in", m["q_in_w"], "W")
        return ("t_rise", m["t_max_k"] - m["t_min_k"], "K")
    if k == "flow3d":
        return ("dp", m["dp_pa"], "Pa")
    if k == "external":
        return ("cd", m["cd"], "-")
    if k in ("cavity", "cavity_of"):
        return ("umin_center", m["umin_center"], "m/s")
    if k == "channel_of":
        return ("umax_outlet", m["umax_outlet"], "m/s")
    if k == "conjugate":
        return ("t_solid_rise", m["t_solid_max_k"] - m["t_inlet_k"], "K")
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
    # relative to the fine answer (Roache): a coarse value must not dilute the change (100 -> 1 -> 0.5 is a 100 %
    # change of the fine answer, not 0.5 %). A fine answer of exactly 0 falls back to the medium one, so that the
    # change still counts; a quantity that is nearly 0 gets a large GCI and fails, which is the honest outcome
    scale = abs(f3) if f3 != 0 else abs(f2)
    rel = abs(e32) / scale if scale > 0 else 0.0
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
    if eng == "builtin-fem" and tpl(case["template"])["physics"] == "electric":
        eng = "builtin-electric"
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
        # the cells the solver really used (snappyHexMesh for turbulent internal flow), else the Gmsh elements
        n = res["metrics"].get("solver_cells") or res["metrics"].get("elements") or 1
        levels.append({"size": size, "elements": n, "h": n ** (-1 / 3), "value": val, "converged": res["converged"],
                       "peak_vm_pa": res["metrics"].get("max_vm_pa")})
        _write_json(sub / "results.json", res)
    g = gci(levels)
    tol = 5.0
    # a study only means something if the mesh really got finer; identical meshes would "agree" perfectly
    refined = all(b["elements"] >= 1.3 * a["elements"] for a, b in zip(levels, levels[1:]))
    # a monotone sequence whose changes do not shrink (p < 1) is not converging, however small one step looks;
    # it may only pass when the last change is already negligible: below a tenth of the tolerance it is remeshing
    # noise (a curved ring converged at 0.07 % then 0.15 %), while a drift like 100 -> 101 -> 102 (1 %) still fails
    settled = g["asymptotic"] or not g["monotone"] or g["rel_change_pct"] <= tol / 10
    passed = all(l["converged"] for l in levels) and g["gci_pct"] <= tol and refined and settled
    fine = json.loads((jd / "levels" / "fine" / "results.json").read_text(encoding="utf-8"))
    for f in ("results.npz", "mesh.npz"):
        if (jd / "levels" / "fine" / f).is_file():
            shutil.copyfile(jd / "levels" / "fine" / f, jd / f)
    conv = {"quantity": name, "unit": unit, "levels": levels, **g, "tolerance_pct": tol, "pass": passed,
            "refined": refined, "settled": settled}
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

ENGINES = {"builtin-fem": run_structural_builtin, "builtin-cavity": run_cavity_builtin,
           "builtin-thermal": run_thermal_builtin, "builtin-electric": run_electric_builtin}


def _acquire_solver_slot(jd: Path) -> Path:
    """One solver job at a time on this machine (meshes and solvers can each use many GB on a 16 GB PC).
    The slot is a directory created atomically; a slot left by a dead process is reclaimed."""
    import os
    import psutil
    # machine-wide (not per workspace): every Studio workspace on this PC shares the same memory
    from .osdirs import data_dir
    base = data_dir()
    base.mkdir(parents=True, exist_ok=True)
    slot = base / "solver.lock"
    # First come, first served: waiters used to race for the slot, and a job queued for an hour lost every race
    # to jobs started after it. Each waiter holds a ticket; only the oldest live ticket may take the slot.
    queue = base / "solver.queue"
    queue.mkdir(exist_ok=True)
    me = {"pid": os.getpid(), "ctime": psutil.Process().create_time(), "job": jd.name}
    ticket = queue / f"{time.time_ns():020d}_{jd.name}.json"
    ticket.write_text(json.dumps(me))

    def drop(t: Path) -> None:
        # Windows refuses to delete a file another process is reading (WinError 32): retry on the next poll instead
        try:
            t.unlink(missing_ok=True)
        except OSError:
            pass

    def ahead() -> str | None:
        """Job name of the oldest live waiter in front of us, or None when we are first in line."""
        for t in sorted(queue.glob("*.json")):
            if t == ticket:
                return None
            try:
                o = json.loads(t.read_text())
                if psutil.pid_exists(o["pid"]) and abs(psutil.Process(o["pid"]).create_time() - o["ctime"]) < 1:
                    return o.get("job", "")                    # an older waiter is alive: it goes first
            except (OSError, ValueError, KeyError, psutil.Error):
                try:
                    if time.time() - t.stat().st_mtime < 10:
                        return ""                              # being written right now
                except OSError:
                    continue                                   # its owner just removed it
            drop(t)                                            # a waiter that died
        return None

    try:
        while True:
            other = ahead()
            if other is not None:
                if (jd / "STOP").exists():
                    raise RuntimeError("stopped while waiting for another job")
                update(jd, state="queued", message_key="job.waiting", message_args={"other": other})
                time.sleep(1.0)
                continue
            try:
                os.mkdir(slot)
            except FileExistsError:
                _wait_for_owner(jd, slot, psutil)
                continue
            # the slot is ours: nothing after this point may lose it
            drop(ticket)
            (slot / "owner.json").write_text(json.dumps({"pid": os.getpid(), "job": jd.name,
                                                         "ctime": psutil.Process().create_time()}))
            return slot
    finally:
        drop(ticket)


def _wait_for_owner(jd: Path, slot: Path, psutil) -> None:
    """The slot is taken: reclaim it if its owner died, otherwise wait a second."""
    o = {}
    try:
        o = json.loads((slot / "owner.json").read_text())
        alive = psutil.pid_exists(o["pid"]) and abs(psutil.Process(o["pid"]).create_time() - o["ctime"]) < 1
    except Exception:
        try:
            alive = (time.time() - slot.stat().st_mtime) < 10        # owner file not written yet
        except OSError:
            return                                                    # released meanwhile: try again at once
    if not alive:
        import shutil
        shutil.rmtree(slot, ignore_errors=True)
        return
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
        if eng == "builtin-fem" and _tp(req["case"]["template"])["physics"] == "electric":
            eng = "builtin-electric"
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
        elif isinstance(exc, MemoryError):                  # the estimate passed but the PC still ran out
            update(jd, state="failed", message_key="err.memory_short", message_args={})
        else:
            update(jd, state="failed", message_key="err.solver", message_args={"detail": f"{type(exc).__name__}: {exc}"})
    finally:
        if lock is not None:
            _release_solver_slot(lock)


if __name__ == "__main__":
    main(sys.argv[1])
