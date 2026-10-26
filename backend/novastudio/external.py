"""External engines: CalculiX (structural) and OpenFOAM ESI (CFD).

The case schema is compiled deterministically into solver input files; the AI never writes solver dictionaries.
Solvers run as separate processes with a fixed argv (no shell).
STATUS: the compilers are unit-tested for their output text; running needs the solvers installed (see config.py).
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import numpy as np

from . import units
from .config import foam_workdir
from .config import find_calculix, find_openfoam

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run(engine: str, case: dict, jd: Path, prog) -> dict:
    if engine == "calculix":
        return run_calculix(case, jd, prog)
    if engine == "openfoam":
        if case.get("bodies"):
            from . import flow3d
            return flow3d.run_conjugate(case, jd, prog, _proc)
        if case.get("flow"):
            from . import flow3d
            try:                                   # hex mesh with wall layers: accurate drag at modest cell counts
                return flow3d.run_external_snappy(case, jd, prog, _proc)
            except RuntimeError as exc:
                if (jd / "STOP").exists():
                    raise
                (jd / "snappy_failed.txt").write_text(str(exc), encoding="utf-8")
                return flow3d.run_external(case, jd, prog, _proc)   # fall back to the tetrahedral pipeline
        if case["template"] == "import-flow":
            from . import flow3d
            return flow3d.run(case, jd, prog, _proc)
        return run_openfoam(case, jd, prog)
    raise ValueError(f"unknown engine {engine}")


MEMORY_ERRORS = ("std::bad_alloc", "cannot satisfy memory request", "Out of memory", "Memory allocation")


def _proc(argv: list[str], cwd: Path, log: Path, jd: Path, env: dict | None = None) -> int:
    """Run a solver; if it died from a (usually transient) shortage of free memory on the PC, wait and retry once."""
    rc = _proc_once(argv, cwd, log, jd, env)
    if rc != 0 and not (jd / "STOP").exists():
        tail = log.read_text(encoding="utf-8", errors="replace")[-4000:] if log.is_file() else ""
        if any(m in tail for m in MEMORY_ERRORS):
            import time
            log.rename(log.with_suffix(log.suffix + ".oom1"))
            time.sleep(20)
            rc = _proc_once(argv, cwd, log, jd, env)
    return rc


SOLVER_LOGS = ("log.simpleFoam", "log.cht", "log.solver")


def _solver_progress(log: Path, cwd: Path, jd: Path) -> None:
    """Map the iteration count in a solver log to job progress 0.15 .. 0.90 (GUI/AI see a moving bar and ETA)."""
    try:
        import re as _re
        from .jobs import update
        cd = (cwd / "system" / "controlDict").read_text(encoding="utf-8", errors="replace")
        end = float(_re.search(r"endTime\s+([0-9.eE+-]+)", cd).group(1))
        with open(log, "rb") as fh:
            fh.seek(0, 2); size = fh.tell(); fh.seek(max(0, size - 20000))
            tail = fh.read().decode("utf-8", errors="replace")
        times = _re.findall(r"^Time = ([0-9.eE+-]+)", tail, _re.M)
        if times and end > 0:
            frac = min(float(times[-1]) / end, 1.0)
            update(jd, state="running", progress=round(0.15 + 0.75 * frac, 3), message_key="job.iterating_n",
                   message_args={"it": int(float(times[-1])), "end": int(end)})
    except Exception:
        pass


def _proc_once(argv: list[str], cwd: Path, log: Path, jd: Path, env: dict | None = None) -> int:
    import time as _time
    with open(log, "w", encoding="utf-8", errors="replace") as fh:
        p = subprocess.Popen(argv, cwd=str(cwd), stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             creationflags=NO_WINDOW, env=env)
        last = 0.0
        while p.poll() is None:
            if log.name in SOLVER_LOGS and _time.time() - last > 3:
                last = _time.time()
                _solver_progress(log, cwd, jd)
            if (jd / "STOP").exists():
                p.terminate()
                break
            try:
                p.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                pass
        return p.returncode if p.returncode is not None else -1


# ------------------------------------------------------------------ CalculiX

CCX_EDGE_ORDER = [(0, 1), (1, 2), (0, 2), (0, 3), (1, 3), (2, 3)]   # C3D10 nodes 5..10 (same as fem_tet10.EDGES)


def _ccx_sections(case, mesh, material_lines) -> list[str]:
    """One material and solid section per body of a multi-material assembly (one for the whole part otherwise)."""
    from .templates import element_groups
    groups = element_groups(case, mesh.get("tet_body", np.zeros(len(mesh["tets"]), int)))
    if len(groups) == 1:
        return ["*MATERIAL, NAME=MAT", *material_lines(groups[0][1]), "*SOLID SECTION, ELSET=EALL, MATERIAL=MAT"]
    out = []
    for i, (idx, props) in enumerate(groups):
        ids = [str(int(e) + 1) for e in idx]
        out.append(f"*ELSET, ELSET=B{i}")
        out += [", ".join(ids[j:j + 16]) for j in range(0, len(ids), 16)]
        out += [f"*MATERIAL, NAME=M{i}", *material_lines(props), f"*SOLID SECTION, ELSET=B{i}, MATERIAL=M{i}"]
    return out


def _ccx_header(case, nodes, tets):
    out = ["** NovaSolver Studio - generated from case %s rev %s" % (case["case_id"], case["revision"]), "*NODE, NSET=NALL"]
    out += [f"{i + 1}, {x:.9e}, {y:.9e}, {z:.9e}" for i, (x, y, z) in enumerate(nodes)]
    out.append("*ELEMENT, TYPE=C3D10, ELSET=EALL")
    out += [f"{e + 1}, " + ", ".join(str(int(n) + 1) for n in t) for e, t in enumerate(tets)]
    return out


# C3D10 / C3D4 face numbering (0-based corner indices) -> CalculiX face label F1..F4
CCX_FACES = [(0, 1, 2), (0, 3, 1), (1, 3, 2), (2, 3, 0)]


def _element_faces(tets: np.ndarray, tri: np.ndarray) -> list[tuple[int, int]]:
    """(element number, face number 1..4) for every boundary triangle."""
    lookup = {}
    for fno, (a, b, c) in enumerate(CCX_FACES, start=1):
        for e, row in enumerate(tets[:, [a, b, c]]):
            lookup[tuple(sorted(row))] = (e + 1, fno)
    return [lookup[tuple(sorted(r[:3]))] for r in tri]


def _nset(name, nodes_):
    s = sorted(int(n) + 1 for n in nodes_)
    return [f"*NSET, NSET={name}"] + [", ".join(map(str, s[i:i + 12])) for i in range(0, len(s), 12)]


def compile_calculix(case: dict, mesh: dict) -> str:
    """Linear static analysis. Loads are the same per-triangle tractions the built-in solver uses."""
    from .fem_tet10 import canonical_tets, tri_areas
    from .run_worker import structural_loads, symmetry_rollers
    nodes, tets = mesh["nodes"], canonical_tets(mesh["nodes"], mesh["tets"])
    mat = case["materials"]["solid"]
    E, nu = units.to_si(mat["E"]), units.to_si(mat["nu"])
    out = _ccx_header(case, nodes, tets)
    fixed_faces, tractions = structural_loads(case, mesh)
    fixed = np.unique(np.concatenate([fa.ravel() for fa in fixed_faces])) if fixed_faces else np.array([], int)
    loads = np.zeros((len(nodes), 3))
    for tri, tt in tractions:
        area = tri_areas(nodes, tri)
        for k in range(3, 6):                      # consistent loads: midside nodes take area/3 each
            np.add.at(loads, tri[:, k], (area / 3)[:, None] * tt)
    bc = []
    if len(fixed):
        out += _nset("FIX", fixed)
        bc.append("FIX, 1, 3, 0.")
    for axis in range(3):                          # symmetry planes: only the normal component is held
        sym = [np.unique(tri) for tri, a in symmetry_rollers(case, mesh) if a == axis]
        if sym:
            out += _nset(f"SYM{'XYZ'[axis]}", np.unique(np.concatenate(sym)))
            bc.append(f"SYM{'XYZ'[axis]}, {axis + 1}, {axis + 1}, 0.")
    out += _ccx_sections(case, mesh, lambda p: ["*ELASTIC", f"{p['E']:.6e}, {p['nu']:.4f}"])
    out += ["*STEP", "*STATIC", "*BOUNDARY", *bc, "*CLOAD"]
    for n in np.nonzero(np.abs(loads).sum(axis=1))[0]:
        for d in range(3):
            if abs(loads[n, d]) > 0:
                out.append(f"{n + 1}, {d + 1}, {loads[n, d]:.9e}")
    out += ["*NODE FILE", "U, RF", "*EL FILE", "S", "*END STEP", ""]
    return "\n".join(out)


def compile_calculix_thermal(case: dict, mesh: dict) -> str:
    """Steady heat conduction: fixed temperatures, surface heat flux (*DFLUX) and convection (*FILM)."""
    from .fem_tet10 import canonical_tets
    from .run_worker import thermal_groups
    nodes, tets = mesh["nodes"], canonical_tets(mesh["nodes"], mesh["tets"])
    out = _ccx_header(case, nodes, tets)
    fixed, fluxes, conv, _ = thermal_groups(case, mesh)
    out += _ccx_sections(case, mesh, lambda p: ["*CONDUCTIVITY", f"{p['k']:.6e}"])
    out += ["*STEP", "*HEAT TRANSFER, STEADY STATE", "1., 1."]
    if fixed:
        out.append("*BOUNDARY")
        done = set()
        for tri, temp in fixed:
            for n in np.unique(tri):
                if int(n) not in done:
                    done.add(int(n))
                    out.append(f"{int(n) + 1}, 11, 11, {temp:.9e}")
    if fluxes:
        out.append("*DFLUX")
        for tri, q in fluxes:
            out += [f"{e}, S{fno}, {q:.9e}" for e, fno in _element_faces(tets, tri)]
    if conv:
        out.append("*FILM")
        for tri, h, tinf in conv:
            out += [f"{e}, F{fno}, {tinf:.9e}, {h:.9e}" for e, fno in _element_faces(tets, tri)]
    out += ["*NODE FILE", "NT", "*END STEP", ""]
    return "\n".join(out)


def parse_frd(path: Path, n_nodes: int) -> dict:
    """Read DISP, STRESS and NDTEMP nodal blocks from an ASCII .frd file."""
    widths = {"DISP": 3, "STRESS": 6, "NDTEMP": 1}
    res, block, vals = {}, None, None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(" -4"):
            name = line[5:13].strip()
            block = name if name in widths else None
            vals = np.zeros((n_nodes, widths[block])) if block else None
        elif block and line.startswith(" -1"):
            node = int(line[3:13])
            vals[node - 1] = [float(line[13 + 12 * i:25 + 12 * i]) for i in range(vals.shape[1])]
        elif block and line.startswith(" -3"):
            res[block] = vals
            block = None
    return res


def run_calculix(case: dict, jd: Path, prog) -> dict:
    from .run_worker import _mesh_for_run, reference_cantilever, reference_thermal_block
    from .templates import get as tpl
    ccx = find_calculix()
    if not ccx:
        raise RuntimeError("CalculiX (ccx) is not installed")
    mesh = _mesh_for_run(case, jd, prog)
    thermal = tpl(case["template"])["physics"] == "thermal"
    wd = jd / "ccx"
    wd.mkdir(exist_ok=True)
    text = compile_calculix_thermal(case, mesh) if thermal else compile_calculix(case, mesh)
    (wd / "job.inp").write_text(text, encoding="utf-8")
    prog("job.solving", 0.3)
    rc = _proc([ccx, "-i", "job"], wd, wd / "ccx.log", jd)
    if rc != 0 or not (wd / "job.frd").is_file():
        raise RuntimeError("CalculiX failed: " + " | ".join((wd / "ccx.log").read_text(errors="replace").splitlines()[-3:]))
    prog("job.post", 0.9)
    r = parse_frd(wd / "job.frd", len(mesh["nodes"]))
    common = {"nodes": int(len(mesh["nodes"])), "elements": int(len(mesh["tets"]))}
    no_ref = {"applicable": False, "why": "no analytic reference for this shape; compare a 'fine' mesh run to check convergence"}
    if thermal:
        T = r["NDTEMP"][:, 0]
        np.savez_compressed(jd / "results.npz", T=T)
        # heat flows from the built-in assembler on CalculiX's temperature field (same mesh, same element)
        from .fem_tet10 import TRI6_M, tri_areas
        from .run_worker import thermal_groups
        fixed, fluxes, conv, order = thermal_groups(case, mesh)
        flows = {}
        for face, (tri, q) in zip(order["flux"], fluxes):
            flows[face] = float(q * tri_areas(mesh["nodes"], tri).sum())
        for face, (tri, h, tinf) in zip(order["convection"], conv):
            a = tri_areas(mesh["nodes"], tri)
            intT = float(np.einsum("eij,ej->", (a / 180.0)[:, None, None] * TRI6_M[None], T[tri]))
            flows[face] = float(h * (tinf * a.sum() - intT))
        metrics = {"t_max_k": float(T.max()), "t_min_k": float(T.min()), "face_flows_w": flows, **common}
        all_flows = _fixed_face_flows(case, mesh, T, flows)
        metrics["face_flows_w"] = all_flows
        from .run_worker import reference_fin
        ref = reference_thermal_block(case, all_flows) if case["template"] == "thermal-block" else \
            reference_fin(case, all_flows) if case["template"] == "fin" else no_ref
        return {"kind": "thermal", "metrics": metrics, "converged": bool(np.isfinite(T).all()),
                "converged_detail": {"note": "steady conduction solve completed"}, "reference": ref}
    U, S = r["DISP"], r["STRESS"]
    vm = np.sqrt(0.5 * ((S[:, 0] - S[:, 1]) ** 2 + (S[:, 1] - S[:, 2]) ** 2 + (S[:, 2] - S[:, 0]) ** 2)
                 + 3 * (S[:, 3] ** 2 + S[:, 4] ** 2 + S[:, 5] ** 2))
    np.savez_compressed(jd / "results.npz", u=U, vm=vm, s=S[:, :6])
    umag = np.linalg.norm(U, axis=1)
    metrics = {"max_disp_m": float(umag.max()), "max_vm_pa": float(vm.max()), **common}
    if case["template"] == "cantilever":
        metrics["tip_disp_m"] = float(-U[np.unique(mesh["face_x1"]), 2].mean())
        ref = reference_cantilever(case, metrics["tip_disp_m"])
    elif case["template"] == "plate-hole":
        from .run_worker import reference_plate_hole
        ref = reference_plate_hole(case, mesh["nodes"], vm, metrics)
    else:
        ref = no_ref
    return {"kind": "structural", "metrics": metrics, "converged": bool(np.isfinite(umag).all()),
            "converged_detail": {"note": "linear static solve completed"}, "reference": ref}


def _fixed_face_flows(case, mesh, T, flows):
    """Heat through fixed-temperature faces = conduction residual, evaluated with the built-in conductivity matrix."""
    from .run_worker import thermal_groups
    fixed, fluxes, conv, order = thermal_groups(case, mesh)
    from .templates import element_k
    out = dict(flows)
    out.update(_residual_flows(mesh, element_k(case, mesh), T, fixed, order["fixed"], fluxes, conv))
    return out


def _residual_flows(mesh, k, T, fixed, faces, fluxes=(), conv=()):
    from .fem_tet10 import DSHAPE, GW, canonical_tets
    import scipy.sparse as sp
    nodes = mesh["nodes"]
    tets = canonical_tets(nodes, mesh["tets"])
    X = nodes[tets]
    Ke = np.zeros((len(tets), 10, 10))
    for g in range(4):
        J = np.einsum("ik,ekj->eij", DSHAPE[g], X)
        dNdx = np.linalg.solve(J, np.broadcast_to(DSHAPE[g], (len(tets), 3, 10)))
        Ke += GW[g] * np.linalg.det(J)[:, None, None] * np.reshape(k, (-1, 1, 1)) * np.einsum("eki,ekj->eij", dNdx, dNdx)
    K = sp.csr_matrix((Ke.ravel(), (np.repeat(tets, 10, axis=1).ravel(), np.tile(tets, (1, 10)).ravel())),
                      shape=(len(nodes), len(nodes)))
    from .fem_tet10 import TRI6_M, tri_areas
    f = np.zeros(len(nodes))
    for tri, q in fluxes:
        a = tri_areas(nodes, tri)
        for c in range(3, 6):
            np.add.at(f, tri[:, c], q * a / 3)
    for tri, h, tinf in conv:                     # convection matrix and load, exactly as the built-in solver
        a = tri_areas(nodes, tri)
        Me = (a / 180.0)[:, None, None] * TRI6_M[None] * h
        K = K + sp.csr_matrix((Me.ravel(), (np.repeat(tri, 6, axis=1).ravel(), np.tile(tri, (1, 6)).ravel())),
                              shape=K.shape)
        for c in range(3, 6):
            np.add.at(f, tri[:, c], h * tinf * a / 3)
    res = K @ T - f
    out, owned = {}, np.zeros(len(nodes), bool)
    for face, (tri, _) in zip(faces, fixed):
        nds = np.setdiff1d(np.unique(tri), np.where(owned)[0])
        owned[nds] = True
        out[face] = float(res[nds].sum())
    return out

# ------------------------------------------------------------------ OpenFOAM (ESI line)

HEADER = """FoamFile
{{
    version     2.0;
    format      ascii;
    class       {cls};
    object      {obj};
}}
// generated by NovaSolver Studio from case {case_id} rev {rev}
"""

CELLS = {"coarse": 33, "normal": 65, "fine": 129}


def compile_openfoam(case: dict) -> dict[str, str]:
    """Return {relative_path: text} for an OpenFOAM case directory."""
    tmpl = case["template"]
    nu = units.to_si(case["materials"]["fluid"]["nu"])
    h = lambda cls, obj: HEADER.format(cls=cls, obj=obj, case_id=case["case_id"], rev=case["revision"])
    files = {}
    n = CELLS[case["mesh"]["size"]]
    if tmpl == "cavity":
        L = units.to_si(case["geometry"]["params"]["size"])
        Ul = units.to_si(case["boundaries"]["y1"]["speed"])
        t = 0.1 * L
        nx, ny = n, n
        verts = [(0, 0, 0), (L, 0, 0), (L, L, 0), (0, L, 0), (0, 0, t), (L, 0, t), (L, L, t), (0, L, t)]
        patches = {"lid": ("wall", "(3 7 6 2)"), "walls": ("wall", "(0 4 7 3) (2 6 5 1) (1 5 4 0)"),
                   "frontAndBack": ("empty", "(0 3 2 1) (4 5 6 7)")}
        dx = L / nx
        dt = 0.5 * dx / max(Ul, 1e-12)
        end = 25 * L / max(Ul, 1e-12)
        solver = "icoFoam"
        ubc = {"lid": f"type fixedValue; value uniform ({Ul:.9g} 0 0);", "walls": "type noSlip;", "frontAndBack": "type empty;"}
        pbc = {"lid": "type zeroGradient;", "walls": "type zeroGradient;", "frontAndBack": "type empty;"}
        control = dict(application=solver, deltaT=dt, endTime=end, writeInterval=end)
    elif tmpl == "channel":
        Lx = units.to_si(case["geometry"]["params"]["length"])
        g = units.to_si(case["geometry"]["params"]["gap"])
        Uin = units.to_si(case["boundaries"]["x0"]["speed"])
        t = 0.5 * g
        ny = max(10, n // 3)
        nx = int(round(ny * Lx / g / 4))
        verts = [(0, 0, 0), (Lx, 0, 0), (Lx, g, 0), (0, g, 0), (0, 0, t), (Lx, 0, t), (Lx, g, t), (0, g, t)]
        patches = {"inlet": ("patch", "(0 4 7 3)"), "outlet": ("patch", "(2 6 5 1)"),
                   "walls": ("wall", "(3 7 6 2) (1 5 4 0)"), "frontAndBack": ("empty", "(0 3 2 1) (4 5 6 7)")}
        solver = "simpleFoam"
        ubc = {"inlet": f"type fixedValue; value uniform ({Uin:.9g} 0 0);", "outlet": "type zeroGradient;",
               "walls": "type noSlip;", "frontAndBack": "type empty;"}
        pbc = {"inlet": "type zeroGradient;", "outlet": "type fixedValue; value uniform 0;",
               "walls": "type zeroGradient;", "frontAndBack": "type empty;"}
        control = dict(application=solver, deltaT=1, endTime=3000, writeInterval=3000)
        files["constant/turbulenceProperties"] = h("dictionary", "turbulenceProperties") + "simulationType laminar;\n"
    else:
        raise ValueError(f"no OpenFOAM compiler for template {tmpl}")

    vtx = "\n".join(f"    ({x:.9g} {y:.9g} {z:.9g})" for x, y, z in verts)
    bnd = "\n".join(f"    {name}\n    {{\n        type {typ};\n        faces ({faces});\n    }}"
                    for name, (typ, faces) in patches.items())
    files["system/blockMeshDict"] = h("dictionary", "blockMeshDict") + f"""
scale 1;
vertices
(
{vtx}
);
blocks
(
    hex (0 1 2 3 4 5 6 7) ({nx} {ny} 1) simpleGrading (1 1 1)
);
boundary
(
{bnd}
);
"""
    files["system/controlDict"] = h("dictionary", "controlDict") + f"""
application     {control['application']};
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         {control['endTime']:.9g};
deltaT          {control['deltaT']:.9g};
writeControl    {'timeStep' if solver == 'icoFoam' else 'timeStep'};
writeInterval   {int(round(control['writeInterval'] / control['deltaT']))};
purgeWrite      1;
writeFormat     ascii;
writePrecision  8;
timeFormat      general;
runTimeModifiable false;
"""
    if solver == "icoFoam":
        files["system/fvSchemes"] = h("dictionary", "fvSchemes") + """
ddtSchemes { default Euler; }
gradSchemes { default Gauss linear; }
divSchemes { default none; div(phi,U) Gauss linear; }
laplacianSchemes { default Gauss linear orthogonal; }
interpolationSchemes { default linear; }
snGradSchemes { default orthogonal; }
"""
        files["system/fvSolution"] = h("dictionary", "fvSolution") + """
solvers
{
    p { solver PCG; preconditioner DIC; tolerance 1e-06; relTol 0.05; }
    pFinal { $p; relTol 0; }
    U { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-05; relTol 0; }
}
PISO { nCorrectors 2; nNonOrthogonalCorrectors 0; pRefCell 0; pRefValue 0; }
"""
    else:
        files["system/fvSchemes"] = h("dictionary", "fvSchemes") + """
ddtSchemes { default steadyState; }
gradSchemes { default Gauss linear; }
divSchemes { default none; div(phi,U) bounded Gauss linearUpwind grad(U); div((nuEff*dev2(T(grad(U))))) Gauss linear; }
laplacianSchemes { default Gauss linear corrected; }
interpolationSchemes { default linear; }
snGradSchemes { default corrected; }
"""
        files["system/fvSolution"] = h("dictionary", "fvSolution") + """
solvers
{
    p { solver GAMG; smoother GaussSeidel; tolerance 1e-07; relTol 0.1; }
    U { solver smoothSolver; smoother GaussSeidel; tolerance 1e-08; relTol 0.1; }
}
SIMPLE { nNonOrthogonalCorrectors 0; consistent yes; residualControl { p 1e-6; U 1e-7; } }
relaxationFactors { equations { U 0.9; ".*" 0.9; } }
"""
    files["constant/transportProperties"] = h("dictionary", "transportProperties") + \
        f"transportModel  Newtonian;\nnu              {nu:.9g};\n"

    def field(name, cls, dims, internal, bcs):
        body = "\n".join(f"    {p}\n    {{\n        {bc}\n    }}" for p, bc in bcs.items())
        return h(cls, name) + f"\ndimensions      {dims};\ninternalField   {internal};\nboundaryField\n{{\n{body}\n}}\n"

    files["0/U"] = field("U", "volVectorField", "[0 1 -1 0 0 0 0]", "uniform (0 0 0)", ubc)
    files["0/p"] = field("p", "volScalarField", "[0 2 -2 0 0 0 0]", "uniform 0", pbc)
    files["meta.json"] = '{"nx": %d, "ny": %d, "solver": "%s"}' % (nx, ny, solver)
    return files


def _read_internal_vectors(path: Path) -> np.ndarray:
    txt = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"internalField\s+nonuniform\s+List<vector>\s*(\d+)\s*\(", txt)
    if not m:
        raise RuntimeError(f"cannot read internalField in {path}")
    n = int(m.group(1))
    vec = re.findall(r"\(([-0-9.eE+]+) ([-0-9.eE+]+) ([-0-9.eE+]+)\)", txt[m.end():])
    return np.array(vec[:n], float)


def run_openfoam(case: dict, jd: Path, prog) -> dict:
    import json as _json
    foam = find_openfoam()
    if not foam:
        raise RuntimeError("OpenFOAM is not installed")
    wd = foam_workdir(jd)
    for rel, text in compile_openfoam(case).items():
        p = wd / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    meta = _json.loads((wd / "meta.json").read_text())
    from .config import openfoam_env
    env = openfoam_env(foam)
    prog("job.meshing", 0.05)
    if _proc([str(Path(foam["bin"]) / "blockMesh.exe"), "-case", str(wd)], wd, wd / "log.blockMesh", jd, env) != 0:
        raise RuntimeError("blockMesh failed: see log.blockMesh")
    prog("job.solving", 0.15)
    if _proc([str(Path(foam["bin"]) / f"{meta['solver']}.exe"), "-case", str(wd)], wd, wd / "log.solver", jd, env) != 0:
        raise RuntimeError(f"{meta['solver']} failed: see log.solver")
    prog("job.post", 0.9)
    times = sorted((d for d in wd.iterdir() if d.is_dir() and re.fullmatch(r"[0-9.eE+-]+", d.name) and d.name != "0"),
                   key=lambda d: float(d.name))
    if not times:
        raise RuntimeError("the solver wrote no result time")
    Uc = _read_internal_vectors(times[-1] / "U").reshape(meta["ny"], meta["nx"], 3)
    log = (wd / "log.solver").read_text(errors="replace")
    res = [float(x) for x in re.findall(r"Solving for Ux, Initial residual = ([0-9.eE+-]+)", log)]
    final_res = res[-1] if res else 1.0
    if case["template"] == "cavity":
        from .cavity_fd import GHIA_RE100_U, GHIA_RE100_Y
        L = units.to_si(case["geometry"]["params"]["size"])
        Ul = units.to_si(case["boundaries"]["y1"]["speed"])
        nu = units.to_si(case["materials"]["fluid"]["nu"])
        yc = (np.arange(meta["ny"]) + 0.5) / meta["ny"]
        uc = Uc[:, meta["nx"] // 2, 0] / Ul
        ug = np.interp(GHIA_RE100_Y, np.r_[0, yc, 1], np.r_[0, uc, 1])
        err = float(np.mean(np.abs(ug - GHIA_RE100_U)) * 100)
        re_ = Ul * L / nu
        ok = abs(re_ - 100) / 100 <= 0.01
        ref = {"applicable": ok, "quantity": "u_centerline", "reference": float(GHIA_RE100_U.min() * Ul),
               "computed": float(uc.min() * Ul), "unit": "m/s", "error_pct": err,
               "tolerance_pct": case["reference"]["tolerance_pct"], "pass": ok and err <= case["reference"]["tolerance_pct"]}
        metrics = {"re": re_, "umin_center": float(uc.min() * Ul), "max_speed": float(np.linalg.norm(Uc, axis=2).max()),
                   "nodes": meta["nx"] * meta["ny"], "elements": meta["nx"] * meta["ny"], "residual": final_res}
        np.savez_compressed(jd / "results.npz", cells=Uc, L=L, U=Ul)
        kind = "cavity_of"
    else:
        Uin = units.to_si(case["boundaries"]["x0"]["speed"])
        g = units.to_si(case["geometry"]["params"]["gap"])
        nu = units.to_si(case["materials"]["fluid"]["nu"])
        col = int(0.9 * meta["nx"])
        umax = float(Uc[:, col, 0].max())
        ref_v = 1.5 * Uin
        err = (umax - ref_v) / ref_v * 100
        ref = {"applicable": True, "quantity": "umax_outlet", "reference": ref_v, "computed": umax, "unit": "m/s",
               "error_pct": err, "tolerance_pct": case["reference"]["tolerance_pct"],
               "pass": abs(err) <= case["reference"]["tolerance_pct"]}
        metrics = {"re": Uin * g / nu, "umax_outlet": umax, "max_speed": float(np.linalg.norm(Uc, axis=2).max()),
                   "nodes": meta["nx"] * meta["ny"], "elements": meta["nx"] * meta["ny"], "residual": final_res}
        np.savez_compressed(jd / "results.npz", cells=Uc, Lx=units.to_si(case["geometry"]["params"]["length"]), g=g)
        kind = "channel_of"
    return {"kind": kind, "metrics": metrics, "converged": final_res < 1e-4,
            "converged_detail": {"residual": final_res, "limit": 1e-4}, "reference": ref}
