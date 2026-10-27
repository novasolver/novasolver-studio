"""Steady incompressible flow inside an imported CAD shape (the solid body is the fluid volume).

Pipeline: Gmsh tetrahedra (MSH 2.2, one physical group per face) -> gmshToFoam -> simpleFoam
(laminar, or k-omega SST when the inlet Reynolds number exceeds 2300) -> results mapped back to the Gmsh mesh.
Roles: inlet (mean speed, flows in normal to the face), outlet (p = 0), wall (no slip).
"""
from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path

import numpy as np

from . import units
from .config import foam_workdir

MESH_DIV = {"coarse": 5, "normal": 8, "fine": 12}       # cells across the smallest inlet/outlet diameter
DUAL_FEATURE_ANGLE = 70                                  # polyDualMesh keeps edges sharper than this as cell edges


def _faces(case):
    return {f["key"]: f for f in case["geometry"].get("faces", [])}


def _hyd_diameter(area: float) -> float:
    return math.sqrt(4 * area / math.pi)


def inlet_reynolds(case: dict) -> float | None:
    faces = _faces(case)
    nu = units.to_si(case["materials"]["fluid"]["nu"])
    res = []
    for k, b in case["boundaries"].items():
        if b.get("role") == "inlet" and k in faces and nu > 0:
            res.append(units.to_si(b["speed"]) * _hyd_diameter(faces[k]["area"]) / nu)
    return max(res) if res else None


def mesh_size(case: dict) -> float:
    faces = _faces(case)
    ends = [faces[k]["area"] for k, b in case["boundaries"].items()
            if b.get("role") in ("inlet", "outlet", "water-inlet", "water-outlet") and k in faces]
    (x0, y0, z0), (x1, y1, z1) = case["geometry"]["bbox"]
    diag = math.dist((x0, y0, z0), (x1, y1, z1))
    h = diag / 30
    if ends:
        h = min(h, _hyd_diameter(min(ends)) / MESH_DIV[case["mesh"]["size"]])
    return h


HEADER = "FoamFile\n{{\n    version 2.0;\n    format ascii;\n    class {cls};\n    object {obj};\n}}\n// NovaSolver Studio case {cid} rev {rev}\n"


def compile_case(case: dict) -> dict[str, str]:
    """System, constant and 0/ files. Patch names are the face keys written by the mesh worker."""
    h = lambda cls, obj: HEADER.format(cls=cls, obj=obj, cid=case["case_id"], rev=case["revision"])
    nu = units.to_si(case["materials"]["fluid"]["nu"])
    re_in = inlet_reynolds(case) or 0.0
    turbulent = re_in > 2300
    faces = _faces(case)
    files = {}
    files["system/controlDict"] = h("dictionary", "controlDict") + """
application simpleFoam;
startFrom startTime; startTime 0; stopAt endTime; endTime 4000; deltaT 1;
writeControl timeStep; writeInterval 4000; purgeWrite 1;
writeFormat ascii; writePrecision 8; timeFormat general; runTimeModifiable false;
"""
    # residualControl ends a converging run early; the cap only matters for fine meshes that need more sweeps.
    # The tetrahedra are turned into polyhedra (polyDualMesh) and the laplacian is fully corrected: on raw tets with
    # 'limited corrected 0.5' a laminar pipe gave the right velocity profile but a 39 % too steep pressure gradient;
    # dual cells + full correction match Hagen-Poiseuille to 0.1 % (2026-10-26, 5 mm straw at Re 20)
    grad = "cellLimited Gauss linear 1" if turbulent else "Gauss linear"
    files["system/fvSchemes"] = h("dictionary", "fvSchemes") + f"""
ddtSchemes {{ default steadyState; }}
gradSchemes {{ default {grad}; }}
divSchemes
{{
    default none;
    div(phi,U) bounded Gauss linearUpwind grad(U);
    div(phi,k) bounded Gauss upwind;
    div(phi,omega) bounded Gauss upwind;
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}}
laplacianSchemes {{ default Gauss linear corrected; }}
interpolationSchemes {{ default linear; }}
snGradSchemes {{ default corrected; }}
wallDist {{ method meshWave; }}
"""
    files["system/fvSolution"] = h("dictionary", "fvSolution") + """
solvers
{
    p { solver GAMG; smoother GaussSeidel; tolerance 1e-07; relTol 0.05; }
    "(U|k|omega)" { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-08; relTol 0.1; }
}
SIMPLE
{
    nNonOrthogonalCorrectors 2;
    consistent yes;
    residualControl { p 1e-4; U 1e-5; "(k|omega)" 1e-5; }
}
relaxationFactors { equations { U 0.7; ".*" 0.7; } fields { p 0.3; } }
"""
    files["constant/transportProperties"] = h("dictionary", "transportProperties") + f"transportModel Newtonian;\nnu {nu:.9g};\n"
    files["constant/turbulenceProperties"] = h("dictionary", "turbulenceProperties") + (
        "simulationType RAS;\nRAS { RASModel kOmegaSST; turbulence on; printCoeffs off; }\n" if turbulent
        else "simulationType laminar;\n")

    def bc(field):
        out = []
        for key, b in case["boundaries"].items():
            role = b.get("role", "wall")
            if field == "U":
                s = f"type surfaceNormalFixedValue; refValue uniform {-units.to_si(b['speed']):.9g};" if role == "inlet" \
                    else "type inletOutlet; inletValue uniform (0 0 0); value uniform (0 0 0);" if role == "outlet" \
                    else "type noSlip;"
            elif field == "p":
                s = "type fixedValue; value uniform 0;" if role == "outlet" else "type zeroGradient;"
            elif field == "k":
                s = "type kqRWallFunction; value uniform 1e-6;" if role == "wall" else \
                    "type turbulentIntensityKineticEnergyInlet; intensity 0.05; value uniform 1e-4;" if role == "inlet" else \
                    "type inletOutlet; inletValue uniform 1e-4; value uniform 1e-4;"
            elif field == "omega":
                s = "type omegaWallFunction; value uniform 1;" if role == "wall" else \
                    f"type turbulentMixingLengthFrequencyInlet; mixingLength {0.07 * _hyd_diameter(faces[key]['area']):.6g}; value uniform 1;" \
                    if role == "inlet" else "type inletOutlet; inletValue uniform 1; value uniform 1;"
            else:  # nut: Spalding's law holds at any y+; tet/dual meshes put the first cell in the buffer layer
                # (y+ 7..33 in a 10 mm pipe at Re 2e4), where nutkWallFunction gave 57 % too little friction (Spalding 38 %)
                s = "type nutUSpaldingWallFunction; value uniform 0;" if role == "wall" else "type calculated; value uniform 0;"
            out.append(f"    {key} {{ {s} }}")
        return "\n".join(out)

    def field(name, cls, dims, internal):
        return h(cls, name) + f"\ndimensions {dims};\ninternalField {internal};\nboundaryField\n{{\n{bc(name)}\n}}\n"

    files["0/U"] = field("U", "volVectorField", "[0 1 -1 0 0 0 0]", "uniform (0 0 0)")
    files["0/p"] = field("p", "volScalarField", "[0 2 -2 0 0 0 0]", "uniform 0")
    if turbulent:
        files["0/k"] = field("k", "volScalarField", "[0 2 -2 0 0 0 0]", "uniform 1e-4")
        files["0/omega"] = field("omega", "volScalarField", "[0 0 -1 0 0 0 0]", "uniform 1")
        files["0/nut"] = field("nut", "volScalarField", "[0 2 -1 0 0 0 0]", "uniform 0")
    files["meta.json"] = json.dumps({"turbulent": turbulent, "re_inlet": re_in})
    return files


def set_wall_types(boundary_file: Path, walls: set[str]) -> None:
    """gmshToFoam makes every patch type 'patch'; walls must be 'wall' for wall functions."""
    txt = boundary_file.read_text(encoding="utf-8", errors="replace")
    def fix(m):
        name, body = m.group(1), m.group(2)
        if name in walls:
            body = re.sub(r"type\s+\w+;", "type wall;", body, count=1)
            body = re.sub(r"\s*physicalType\s+\w+;", "", body)
        return f"{name}\n    {{{body}}}"
    txt = re.sub(r"(\w+)\s*\n\s*\{([^{}]*)\}", fix, txt)
    boundary_file.write_text(txt, encoding="utf-8", newline="\n")


def _internal(path: Path, vector: bool) -> np.ndarray:
    txt = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"internalField\s+(uniform|nonuniform)", txt)
    if m and m.group(1) == "uniform":
        return None
    m = re.search(r"internalField\s+nonuniform\s+List<(?:vector|scalar)>\s*(\d+)\s*\(", txt)
    n = int(m.group(1))
    body = txt[m.end():]
    if vector:
        return np.array(re.findall(r"\(([-0-9.eE+]+) ([-0-9.eE+]+) ([-0-9.eE+]+)\)", body)[:n], float)
    return np.array(body.split(")")[0].split(), float)[:n]


def _boundary_values(path: Path, patch: str, vector: bool) -> np.ndarray | None:
    txt = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(rf"\n\s*{patch}\s*\{{(.*?)\n\s*\}}", txt, re.S)
    if not m:
        return None
    body = m.group(1)
    u = re.search(r"value\s+uniform\s+(\(([^)]*)\)|[-0-9.eE+]+)", body)
    nm = re.search(r"value\s+nonuniform\s+List<(?:vector|scalar)>\s*(\d+)\s*\(", body)
    if nm:
        rest = body[nm.end():]
        if vector:
            return np.array(re.findall(r"\(([-0-9.eE+]+) ([-0-9.eE+]+) ([-0-9.eE+]+)\)", rest)[:int(nm.group(1))], float)
        return np.array(rest.split(")")[0].split(), float)[:int(nm.group(1))]
    if u:
        return np.array([float(x) for x in (u.group(2) or u.group(1)).split()], float)[None, :] if vector \
            else np.array([float(u.group(1))])
    return None


# turbulent: core cells across the smallest inlet/outlet; a ratio of about 1.4 between levels keeps the convergence
# study readable (8/10/14 refined too little to separate the discretisation error from noise)
SNAPPY_ACROSS = {"coarse": 7, "normal": 10, "fine": 14}
WALL_YPLUS = 60          # first-layer target (sets ~30 at the wall cell centre: inside the wall-function range)
WALL_LAYERS = 3


def snappy_internal_files(case: dict, mesh: dict) -> tuple[dict[str, str], dict]:
    """Turbulent internal flow: hex-dominant mesh with wall layers (snappyHexMesh) inside the fluid surface.
    Each Studio face is an STL region named by its key, so patches keep the names compile_case uses. On the
    dual-tet mesh a 10 mm pipe at Re 2e4 gave 38 % too little wall friction (y+ in the buffer layer, too few
    cells across); this mesh gives Blasius within 3 % (2026-10-27)."""
    nodes = mesh["nodes"]
    roles = {k: b.get("role") for k, b in case["boundaries"].items()}
    walls = [k for k, r in roles.items() if r == "wall"]
    stl = []
    for key in case["boundaries"]:
        tri = mesh.get(f"face_{key}")
        if tri is None:
            continue
        stl.append(f"solid {key}")
        for t in tri[:, :3]:
            p = nodes[t]
            n = np.cross(p[1] - p[0], p[2] - p[0])
            n = n / (np.linalg.norm(n) + 1e-30)
            stl.append(f" facet normal {n[0]:.6e} {n[1]:.6e} {n[2]:.6e}\n  outer loop\n" +
                       "\n".join(f"   vertex {x:.9e} {y:.9e} {z:.9e}" for x, y, z in p) + "\n  endloop\n endfacet")
        stl.append(f"endsolid {key}")
    faces = _faces(case)
    ends = [faces[k]["area"] for k, r in roles.items() if r in ("inlet", "outlet") and k in faces]
    dh = min(_hyd_diameter(a) for a in ends)
    h = dh / SNAPPY_ACROSS[case["mesh"]["size"]]
    lo, hi = nodes.min(axis=0) - 2 * h, nodes.max(axis=0) + 2 * h
    n = np.maximum(np.ceil((hi - lo) / h).astype(int), 1)
    nu = units.to_si(case["materials"]["fluid"]["nu"])
    re_in = inlet_reynolds(case) or 1e4
    utau = re_in * nu / dh * math.sqrt(0.316 * re_in ** -0.25 / 8)      # Blasius estimate of the friction velocity
    # the same wall layer on every mesh level (only the core is refined): a convergence study must not move the
    # first cell between the buffer layer and the log layer
    y1 = min(2 * WALL_YPLUS * nu / utau, 0.08 * dh)
    tets = mesh["tets"][:, :4]
    vol = np.abs(np.einsum("ij,ij->i", np.cross(nodes[tets[:, 1]] - nodes[tets[:, 0]], nodes[tets[:, 2]] - nodes[tets[:, 0]]),
                           nodes[tets[:, 3]] - nodes[tets[:, 0]]))
    inside = nodes[tets[int(np.argmax(vol))]].mean(axis=0)              # centre of the biggest tet: deep in the fluid
    hdr = lambda cls, obj: HEADER.format(cls=cls, obj=obj, cid=case["case_id"], rev=case["revision"])
    v = lambda p: f"({p[0]:.9g} {p[1]:.9g} {p[2]:.9g})"
    X0, Y0, Z0 = lo; X1, Y1, Z1 = hi
    verts = [(X0, Y0, Z0), (X1, Y0, Z0), (X1, Y1, Z0), (X0, Y1, Z0), (X0, Y0, Z1), (X1, Y0, Z1), (X1, Y1, Z1), (X0, Y1, Z1)]
    names = " ".join(f"{k} {{ name {k}; }}" for k in case["boundaries"])
    regions = "\n".join(f"        {k} {{ level (0 0); patchInfo {{ type {'wall' if roles[k] == 'wall' else 'patch'}; }} }}"
                        for k in case["boundaries"])
    layers = "\n".join(f"        {k} {{ nSurfaceLayers {WALL_LAYERS}; }}" for k in walls)
    files = {
        "constant/triSurface/fluid.stl": "\n".join(stl) + "\n",
        "system/blockMeshDict": hdr("dictionary", "blockMeshDict") + "scale 1;\nvertices\n(\n" + "\n".join(
            f"    {v(p)}" for p in verts) + f"\n);\nblocks\n(\n    hex (0 1 2 3 4 5 6 7) ({n[0]} {n[1]} {n[2]}) simpleGrading (1 1 1)\n);\n"
            "boundary\n(\n    box { type patch; faces ((0 4 7 3) (1 2 6 5) (0 1 5 4) (3 7 6 2) (0 3 2 1) (4 5 6 7)); }\n);\n",
        "system/surfaceFeatureExtractDict": hdr("dictionary", "surfaceFeatureExtractDict") +
            "fluid.stl\n{\n    extractionMethod extractFromSurface;\n    extractFromSurfaceCoeffs { includedAngle 150; }\n"
            "    writeObj no;\n}\n",
        "system/meshQualityDict": hdr("dictionary", "meshQualityDict") + "#includeEtc \"caseDicts/meshQualityDict\"\n",
        "system/snappyHexMeshDict": hdr("dictionary", "snappyHexMeshDict") + f"""
castellatedMesh true; snap true; addLayers true;
geometry {{ fluid.stl {{ type triSurfaceMesh; name fluid; regions {{ {names} }} }} }}
castellatedMeshControls
{{
    maxLocalCells 3000000; maxGlobalCells 6000000; minRefinementCells 0; maxLoadUnbalance 0.1; nCellsBetweenLevels 2;
    features ( {{ file "fluid.eMesh"; level 0; }} );
    refinementSurfaces {{ fluid {{ level (0 0); regions {{
{regions}
    }} }} }}
    resolveFeatureAngle 30; refinementRegions {{ }}
    locationInMesh {v(inside)};
    allowFreeStandingZoneFaces false;
}}
snapControls {{ nSmoothPatch 3; tolerance 2.0; nSolveIter 100; nRelaxIter 5; nFeatureSnapIter 10;
               implicitFeatureSnap false; explicitFeatureSnap true; multiRegionFeatureSnap false; }}
addLayersControls
{{
    relativeSizes false;
    layers {{
{layers}
    }}
    firstLayerThickness {y1:.6g}; expansionRatio 1.2; minThickness {0.3 * y1:.6g}; nGrow 0;
    featureAngle 130; slipFeatureAngle 30; nRelaxIter 5; nSmoothSurfaceNormals 1; nSmoothNormals 3;
    nSmoothThickness 10; maxFaceThicknessRatio 0.5; maxThicknessToMedialRatio 0.3; minMedialAxisAngle 90;
    nBufferCellsNoExtrude 0; nLayerIter 50;
}}
meshQualityControls {{ #include "meshQualityDict" nSmoothScale 4; errorReduction 0.75; }}
mergeTolerance 1e-6;
"""}
    return files, {"cell_size_m": h, "first_layer_m": y1, "layers": WALL_LAYERS}


def run(case: dict, jd: Path, prog, proc) -> dict:
    """proc(argv, cwd, log, jd, env) -> returncode (external._proc)."""
    from scipy.spatial import cKDTree
    from .config import find_openfoam, openfoam_env
    from .fem_tet10 import tri_areas
    from .run_worker import _mesh_for_run
    foam = find_openfoam()
    if not foam:
        raise RuntimeError("OpenFOAM is not installed")
    mesh = _mesh_for_run(case, jd, prog)            # also writes mesh.msh next to mesh.npz
    from .geometry import mesh_dir
    msh = mesh_dir(case) / "mesh.msh"
    wd = foam_workdir(jd)
    for rel, text in compile_case(case).items():
        p = wd / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    (wd / "mesh.msh").write_bytes(msh.read_bytes())
    meta = json.loads((wd / "meta.json").read_text())
    env = openfoam_env(foam)
    exe = lambda n: str(Path(foam["bin"]) / f"{n}.exe")
    prog("job.meshing", 0.08)
    walls = {k for k, b in case["boundaries"].items() if b.get("role") == "wall"}
    wall_mesh = None
    if meta["turbulent"]:
        # wall layers: the Gmsh mesh stays for display and probes, the solver gets a snappyHexMesh mesh
        sfiles, wall_mesh = snappy_internal_files(case, mesh)
        for rel, text in sfiles.items():
            p = wd / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8", newline="\n")
        for step, frac in (("blockMesh", 0.09), ("surfaceFeatureExtract", 0.1), ("snappyHexMesh", 0.11)):
            prog("job.meshing", frac)
            args = [exe(step), "-case", str(wd)] + (["-overwrite"] if step == "snappyHexMesh" else [])
            if proc(args, wd, wd / f"log.{step}", jd, env) != 0:
                tail = (wd / f"log.{step}").read_text(errors="replace").strip().splitlines()[-3:]
                raise RuntimeError(f"{step} failed: " + " | ".join(tail))
    else:
        if proc([exe("gmshToFoam"), "-case", str(wd), str(wd / "mesh.msh")], wd, wd / "log.gmshToFoam", jd, env) != 0:
            raise RuntimeError("gmshToFoam failed: see log.gmshToFoam")
        set_wall_types(wd / "constant" / "polyMesh" / "boundary", walls)
        # one polyhedron per tet node: far more accurate wall friction than raw tetrahedra (see compile_case)
        if proc([exe("polyDualMesh"), "-case", str(wd), "-overwrite", str(DUAL_FEATURE_ANGLE)], wd,
                wd / "log.polyDualMesh", jd, env) != 0:
            raise RuntimeError("polyDualMesh failed: see log.polyDualMesh")
    set_wall_types(wd / "constant" / "polyMesh" / "boundary", walls)
    prog("job.solving", 0.15)
    rc = proc([exe("simpleFoam"), "-case", str(wd)], wd, wd / "log.simpleFoam", jd, env)
    if rc != 0:
        tail = (wd / "log.simpleFoam").read_text(errors="replace").strip().splitlines()[-4:]
        raise RuntimeError("simpleFoam failed: " + " | ".join(tail))
    prog("job.post", 0.9)
    proc([exe("postProcess"), "-case", str(wd), "-func", "writeCellCentres", "-latestTime"], wd, wd / "log.post", jd, env)
    if wall_mesh is not None:                         # wall functions hold for y+ about 30..300: report what we got
        proc([exe("simpleFoam"), "-case", str(wd), "-postProcess", "-func", "yPlus", "-latestTime"], wd,
             wd / "log.yPlus", jd, env)
        yp = re.findall(r"y\+ : min = ([0-9.eE+-]+), max = ([0-9.eE+-]+), average = ([0-9.eE+-]+)",
                        (wd / "log.yPlus").read_text(errors="replace"))
        if yp:
            wall_mesh["yplus_avg"] = float(np.mean([float(a) for _, _, a in yp]))
            wall_mesh["yplus_min"] = float(min(float(a) for a, _, _ in yp))
    times = sorted((d for d in wd.iterdir() if d.is_dir() and re.fullmatch(r"[0-9.eE+-]+", d.name) and d.name != "0"),
                   key=lambda d: float(d.name))
    if not times:
        raise RuntimeError("simpleFoam wrote no result")
    last = times[-1]
    U = _internal(last / "U", True)
    p = _internal(last / "p", False)
    C = _internal(last / "C", True)
    log = (wd / "log.simpleFoam").read_text(errors="replace")
    resid = [float(x) for x in re.findall(r"Solving for Ux, Initial residual = ([0-9.eE+-]+)", log)]
    iters = len(re.findall(r"^Time = ", log, re.M))
    converged_res = resid[-1] if resid else 1.0

    # dual mesh: each polyhedron belongs to one Gmsh node, whose value is the nearest cell centre's
    nodes, tets = mesh["nodes"], mesh["tets"][:, :4]
    dist, idx = cKDTree(C).query(nodes)
    nodal = np.column_stack([U[idx], p[idx]])
    for key in walls:                                   # no-slip: the wall itself does not move
        if f"face_{key}" in mesh:
            nodal[np.unique(mesh[f"face_{key}"]), :3] = 0.0
    rho = units.to_si(case["materials"]["fluid"].get("rho", {"value": 1000, "unit": "kg/m3"}))

    # flow rates and pressure drop from boundary values
    q_in = q_out = 0.0
    p_in = []
    for key, b in case["boundaries"].items():
        tri = mesh.get(f"face_{key}")
        if tri is None:
            continue
        a = tri_areas(nodes, tri).sum()
        if b.get("role") == "inlet":
            q_in += units.to_si(b["speed"]) * a
            # zeroGradient patches carry no stored value: area-weighted mean of the nodal pressure on the face
            ta = tri_areas(nodes, tri)
            p_in.append(float((nodal[tri[:, :3], 3].mean(axis=1) * ta).sum() / ta.sum()) * rho)
        elif b.get("role") == "outlet":
            # OpenFOAM's own face fluxes: nodal velocities are zero on the wall rim and would read low
            phi = _boundary_values(last / "phi", key, False) if (last / "phi").is_file() else None
            if phi is not None and len(phi) > 1:
                q_out += float(phi.sum())
                continue
            from .fem_tet10 import outward_normals
            n = outward_normals(nodes, np.asarray(mesh["tets"]), tri)
            un = np.einsum("ij,ij->i", nodal[tri[:, :3], :3].mean(axis=1), n)
            q_out += float((un * tri_areas(nodes, tri)).sum())
    face_flux = {}                                      # exact volume flow out through each open face (phi)
    if (last / "phi").is_file():
        for key, b in case["boundaries"].items():
            if b.get("role") in ("inlet", "outlet"):
                phi = _boundary_values(last / "phi", key, False)
                if phi is not None and len(phi) > 1:
                    face_flux[key] = float(phi.sum())
    q_in_solver = -sum(q for k, q in face_flux.items() if case["boundaries"][k].get("role") == "inlet")
    if q_in_solver > 0:
        # the solver's own inflow: a snappyHexMesh inlet is snapped to the surface, not the Gmsh triangles
        q_in = q_in_solver
    balance = abs(q_in - q_out) / q_in if q_in > 0 else 1.0
    np.savez_compressed(jd / "results.npz", U=nodal[:, :3], p=nodal[:, 3] * rho)
    speed = np.linalg.norm(nodal[:, :3], axis=1)
    metrics = {"re": meta["re_inlet"], "turbulent": meta["turbulent"], "flow_rate_m3s": q_in, "outflow_m3s": q_out,
               "mass_balance": balance, "dp_pa": (max(p_in) if p_in else 0.0), "max_speed": float(speed.max()),
               "iterations": iters, "residual": converged_res, "nodes": int(len(nodes)), "elements": int(len(tets)),
               "map_max_dist": float(dist.max()), "face_flux_m3s": face_flux,
               "solver_cells": len(C), "mesher": "snappyHexMesh+layers" if wall_mesh else "gmsh+polyDualMesh"}
    if wall_mesh:
        metrics["wall_mesh"] = wall_mesh
    converged = bool(converged_res < 1e-3 and balance < 0.02 and np.isfinite(speed).all())
    return {"kind": "flow3d", "metrics": metrics, "converged": converged,
            "converged_detail": {"residual": converged_res, "limit": 1e-3, "mass_balance": balance, "balance_limit": 0.02},
            "reference": {"applicable": False,
                          "why": "no analytic reference for this shape; compare a 'fine' mesh run to check convergence"}}


def slice_plane(nodes, tets, values, origin, normal):
    """Cut tetrahedra with a plane. Returns triangle soup (positions (m,3), indices, interpolated values)."""
    d = (nodes - origin) @ normal
    D = d[tets]
    s = np.sign(D)
    cut = (s.min(axis=1) < 0) & (s.max(axis=1) > 0)
    P, V, I = [], [], []
    edges = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]
    for e in np.where(cut)[0]:
        t = tets[e]
        pts, vals = [], []
        for a, b in edges:
            da, db = D[e, a], D[e, b]
            if (da < 0) != (db < 0):
                w = da / (da - db)
                pts.append(nodes[t[a]] + w * (nodes[t[b]] - nodes[t[a]]))
                vals.append(values[t[a]] + w * (values[t[b]] - values[t[a]]))
        if len(pts) < 3:
            continue
        pts = np.array(pts)
        c = pts.mean(axis=0)
        ax1 = pts[0] - c
        ax2 = np.cross(normal, ax1)
        order = np.argsort(np.arctan2((pts - c) @ ax2, (pts - c) @ ax1))
        base = len(P)
        P.extend(pts[order]); V.extend(np.array(vals)[order])
        for k in range(1, len(order) - 1):
            I.append([base, base + k, base + k + 1])
    return np.array(P), np.array(I, int), np.array(V)


# ------------------------------------------------------------------ external flow (body in a tunnel)

DIRS = {"+x": (1, 0, 0), "-x": (-1, 0, 0), "+y": (0, 1, 0), "-y": (0, -1, 0), "+z": (0, 0, 1), "-z": (0, 0, -1)}


def frontal_area(nodes: np.ndarray, tri: np.ndarray, direction: np.ndarray, n: int = 500) -> float:
    """Projected (shadow) area of the body seen along the flow direction, by rasterising its triangles."""
    d = direction / np.linalg.norm(direction)
    a = np.array([1.0, 0, 0]) if abs(d[0]) < 0.9 else np.array([0, 1.0, 0])
    e1 = np.cross(d, a); e1 /= np.linalg.norm(e1); e2 = np.cross(d, e1)
    P = np.stack([nodes @ e1, nodes @ e2], 1)
    lo, hi = P.min(axis=0), P.max(axis=0)
    span = (hi - lo).max() * 1.02
    px = span / n
    grid = np.zeros((n + 2, n + 2), bool)
    T = P[tri[:, :3]]
    for t in T:
        mn = np.floor((t.min(axis=0) - lo) / px).astype(int); mx = np.ceil((t.max(axis=0) - lo) / px).astype(int)
        xs, ys = np.meshgrid(np.arange(mn[0], mx[0] + 1), np.arange(mn[1], mx[1] + 1), indexing="ij")
        q = np.stack([xs.ravel(), ys.ravel()], 1) * px + lo + px / 2
        v0, v1 = t[1] - t[0], t[2] - t[0]
        den = v0[0] * v1[1] - v0[1] * v1[0]
        if abs(den) < 1e-30:
            continue
        w = q - t[0]
        s = (w[:, 0] * v1[1] - w[:, 1] * v1[0]) / den
        r = (v0[0] * w[:, 1] - v0[1] * w[:, 0]) / den
        inside = (s >= 0) & (r >= 0) & (s + r <= 1)
        grid[np.clip(xs.ravel()[inside], 0, n + 1), np.clip(ys.ravel()[inside], 0, n + 1)] = True
    return float(grid.sum() * px * px)


def schiller_naumann(re: float) -> float:
    return 24.0 / re * (1 + 0.15 * re ** 0.687)


def compile_external(case: dict, aref: float, lref: float, center, extra_functions: str = "") -> dict[str, str]:
    h = lambda cls, obj: HEADER.format(cls=cls, obj=obj, cid=case["case_id"], rev=case["revision"])
    nu = units.to_si(case["materials"]["fluid"]["nu"])
    U = units.to_si(case["flow"]["speed"])
    d = np.array(DIRS[case["flow"]["direction"]], float)
    Uv = U * d
    re = U * lref / nu
    turbulent = re > 300
    lift = np.array([0, 0, 1.0]) if abs(d[2]) < 0.9 else np.array([0, 1.0, 0])
    pitch = np.cross(lift, d)
    vec = lambda v: "(" + " ".join(f"{x:.9g}" for x in v) + ")"
    files = {}
    files["system/controlDict"] = h("dictionary", "controlDict") + f"""
application simpleFoam;
startFrom startTime; startTime 0; stopAt endTime; endTime 1500; deltaT 1;
writeControl timeStep; writeInterval 1500; purgeWrite 1;
writeFormat ascii; writePrecision 8; timeFormat general; runTimeModifiable false;
functions
{{
    forceCoeffs1
    {{
        type forceCoeffs; libs (forces); writeControl timeStep; writeInterval 1;
        patches (body); rho rhoInf; rhoInf 1; CofR {vec(center)};
        liftDir {vec(lift)}; dragDir {vec(d)}; pitchAxis {vec(pitch)};
        magUInf {U:.9g}; lRef {lref:.9g}; Aref {aref:.9g};
    }}
{extra_functions}
}}
"""
    # laminar: unlimited second-order schemes (less numerical diffusion -> correct wake and drag); RANS: limited
    grad = "Gauss linear" if not turbulent else "cellLimited Gauss linear 1"
    divu = "Gauss linear" if not turbulent else "bounded Gauss linearUpwind grad(U)"
    files["system/fvSchemes"] = h("dictionary", "fvSchemes") + f"""
ddtSchemes {{ default steadyState; }}
gradSchemes {{ default {grad}; }}
divSchemes
{{
    default none;
    div(phi,U) {"bounded " if turbulent else ""}{divu.replace("bounded ", "")};
    div(phi,k) bounded Gauss upwind;
    div(phi,omega) bounded Gauss upwind;
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}}
laplacianSchemes {{ default Gauss linear limited corrected 0.5; }}
interpolationSchemes {{ default linear; }}
snGradSchemes {{ default limited corrected 0.5; }}
wallDist {{ method meshWave; }}
"""
    files["system/fvSolution"] = h("dictionary", "fvSolution") + """
solvers
{
    p { solver GAMG; smoother GaussSeidel; tolerance 1e-07; relTol 0.05; }
    "(U|k|omega)" { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-08; relTol 0.1; }
}
SIMPLE { nNonOrthogonalCorrectors 1; consistent yes; residualControl { p 1e-4; U 1e-5; "(k|omega)" 1e-5; } }
relaxationFactors { equations { U 0.7; ".*" 0.7; } fields { p 0.3; } }
"""
    files["constant/transportProperties"] = h("dictionary", "transportProperties") + f"transportModel Newtonian;\nnu {nu:.9g};\n"
    files["constant/turbulenceProperties"] = h("dictionary", "turbulenceProperties") + (
        "simulationType RAS;\nRAS { RASModel kOmegaSST; turbulence on; printCoeffs off; }\n" if turbulent
        else "simulationType laminar;\n")
    k_in = 1.5 * (0.01 * U) ** 2
    om_in = math.sqrt(k_in) / (0.09 ** 0.25 * 0.1 * lref)
    bcs = {
        "U": {"inlet": f"type fixedValue; value uniform {vec(Uv)};", "outlet": "type inletOutlet; inletValue uniform (0 0 0); value uniform (0 0 0);",
              "sides": "type slip;", "body": "type noSlip;"},
        "p": {"inlet": "type zeroGradient;", "outlet": "type fixedValue; value uniform 0;", "sides": "type slip;", "body": "type zeroGradient;"},
        "k": {"inlet": f"type fixedValue; value uniform {k_in:.6g};", "outlet": f"type inletOutlet; inletValue uniform {k_in:.6g}; value uniform {k_in:.6g};",
              "sides": "type slip;", "body": f"type kqRWallFunction; value uniform {k_in:.6g};"},
        "omega": {"inlet": f"type fixedValue; value uniform {om_in:.6g};", "outlet": f"type inletOutlet; inletValue uniform {om_in:.6g}; value uniform {om_in:.6g};",
                  "sides": "type slip;", "body": f"type omegaWallFunction; value uniform {om_in:.6g};"},
        "nut": {"inlet": "type calculated; value uniform 0;", "outlet": "type calculated; value uniform 0;", "sides": "type slip;",
                "body": "type nutkWallFunction; value uniform 0;"},
    }
    internal = {"U": f"uniform {vec(Uv)}", "p": "uniform 0", "k": f"uniform {k_in:.6g}", "omega": f"uniform {om_in:.6g}", "nut": "uniform 0"}
    dims = {"U": "[0 1 -1 0 0 0 0]", "p": "[0 2 -2 0 0 0 0]", "k": "[0 2 -2 0 0 0 0]", "omega": "[0 0 -1 0 0 0 0]", "nut": "[0 2 -1 0 0 0 0]"}
    for name in (["U", "p", "k", "omega", "nut"] if turbulent else ["U", "p"]):
        cls = "volVectorField" if name == "U" else "volScalarField"
        body = "\n".join(f"    {pt} {{ {s} }}" for pt, s in bcs[name].items())
        files[f"0/{name}"] = h(cls, name) + f"\ndimensions {dims[name]};\ninternalField {internal[name]};\nboundaryField\n{{\n{body}\n}}\n"
    files["meta.json"] = json.dumps({"turbulent": turbulent, "re": re, "aref": aref, "lref": lref, "U": U})
    return files


def _read_coefficients(wd: Path) -> dict | None:
    hits = sorted(wd.glob("postProcessing/forceCoeffs1/*/coefficient*.dat"))
    if not hits:
        return None
    cols, rows = None, []
    for line in hits[-1].read_text(errors="replace").splitlines():
        if line.startswith("#"):
            parts = line.lstrip("#").split()
            if parts and parts[0] == "Time":
                cols = parts
            continue
        if line.strip():
            rows.append([float(x) for x in line.split()])
    if not cols or not rows:
        return None
    a = np.array(rows)
    return {c: a[:, i] for i, c in enumerate(cols) if i < a.shape[1]}


def run_external(case: dict, jd: Path, prog, proc) -> dict:
    from scipy.spatial import cKDTree
    from .config import find_openfoam, openfoam_env
    from .geometry import mesh_dir
    from .run_worker import _mesh_for_run
    foam = find_openfoam()
    if not foam:
        raise RuntimeError("OpenFOAM is not installed")
    mesh = _mesh_for_run(case, jd, prog)
    nodes, tets = mesh["nodes"], mesh["tets"][:, :4]
    body = mesh["face_body"]
    d = np.array(DIRS[case["flow"]["direction"]], float)
    aref = frontal_area(nodes, body, d)
    lref = math.sqrt(4 * aref / math.pi)                       # equivalent diameter of the frontal area
    center = nodes[np.unique(body[:, :3])].mean(axis=0)
    wd = foam_workdir(jd)
    for rel, text in compile_external(case, aref, lref, center).items():
        p = wd / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    (wd / "mesh.msh").write_bytes((mesh_dir(case) / "mesh.msh").read_bytes())
    meta = json.loads((wd / "meta.json").read_text())
    env = openfoam_env(foam)
    exe = lambda n: str(Path(foam["bin"]) / f"{n}.exe")
    prog("job.meshing", 0.08)
    if proc([exe("gmshToFoam"), "-case", str(wd), str(wd / "mesh.msh")], wd, wd / "log.gmshToFoam", jd, env) != 0:
        raise RuntimeError("gmshToFoam failed: see log.gmshToFoam")
    set_wall_types(wd / "constant" / "polyMesh" / "boundary", {"body"})
    prog("job.solving", 0.15)
    if proc([exe("simpleFoam"), "-case", str(wd)], wd, wd / "log.simpleFoam", jd, env) != 0:
        tail = (wd / "log.simpleFoam").read_text(errors="replace").strip().splitlines()[-4:]
        raise RuntimeError("simpleFoam failed: " + " | ".join(tail))
    prog("job.post", 0.9)
    proc([exe("postProcess"), "-case", str(wd), "-func", "writeCellCentres", "-latestTime"], wd, wd / "log.post", jd, env)
    times = sorted((x for x in wd.iterdir() if x.is_dir() and re.fullmatch(r"[0-9.eE+-]+", x.name) and x.name != "0"),
                   key=lambda x: float(x.name))
    last = times[-1]
    U = _internal(last / "U", True); p = _internal(last / "p", False); C = _internal(last / "C", True)
    cent = nodes[tets].mean(axis=1)
    dist, idx = cKDTree(C).query(cent)
    acc = np.zeros((len(nodes), 4)); cnt = np.zeros(len(nodes))
    for c in range(4):
        np.add.at(acc, tets[:, c], np.column_stack([U[idx], p[idx]]))
        np.add.at(cnt, tets[:, c], 1)
    nodal = acc / np.maximum(cnt, 1)[:, None]
    rho = units.to_si(case["materials"]["fluid"].get("rho", {"value": 1000, "unit": "kg/m3"}))
    np.savez_compressed(jd / "results.npz", U=nodal[:, :3], p=nodal[:, 3] * rho)
    co = _read_coefficients(wd) or {}
    cd_hist = co.get("Cd", np.array([np.nan]))
    cl_hist = co.get("Cl", np.array([np.nan]))
    tail = cd_hist[-max(10, len(cd_hist) // 10):]
    cd, cl = float(cd_hist[-1]), float(cl_hist[-1])
    cd_var = float(np.ptp(tail) / abs(np.mean(tail))) if len(tail) > 1 and np.mean(tail) else 1.0
    log = (wd / "log.simpleFoam").read_text(errors="replace")
    resid = [float(x) for x in re.findall(r"Solving for Ux, Initial residual = ([0-9.eE+-]+)", log)]
    res_last = resid[-1] if resid else 1.0
    Uinf = meta["U"]
    metrics = {"cd": cd, "cl": cl, "drag_n": 0.5 * rho * Uinf ** 2 * aref * cd, "re": meta["re"], "aref_m2": aref,
               "lref_m": lref, "turbulent": meta["turbulent"], "cd_variation": cd_var, "residual": res_last,
               "max_speed": float(np.linalg.norm(nodal[:, :3], axis=1).max()), "iterations": len(resid),
               "nodes": int(len(nodes)), "elements": int(len(tets))}
    converged = bool(cd_var < 0.01 and np.isfinite(cd))
    ref = {"applicable": False, "why": "no analytic reference for this shape"}
    if case["template"] == "sphere-drag":
        if 1 <= meta["re"] <= 800 and not meta["turbulent"]:
            cref = schiller_naumann(meta["re"])
            err = (cd - cref) / cref * 100
            ref = {"applicable": True, "quantity": "cd", "reference": cref, "computed": cd, "unit": "-", "error_pct": err,
                   "tolerance_pct": case["reference"]["tolerance_pct"], "pass": abs(err) <= case["reference"]["tolerance_pct"],
                   "metric": "Schiller-Naumann: Cd = 24/Re (1 + 0.15 Re^0.687)"}
        else:
            ref = {"applicable": False, "why": "the Schiller-Naumann comparison is for steady laminar flow (Re <= 300 here)"}
    return {"kind": "external", "metrics": metrics, "converged": converged,
            "converged_detail": {"cd_variation_last10pct": cd_var, "limit": 0.01, "residual": res_last}, "reference": ref}


# ------------------------------------------------------------------ conjugate heat transfer (water + solids)

def _boundary_patches(path: Path) -> dict[str, str]:
    txt = path.read_text(encoding="utf-8", errors="replace")
    return {m.group(1): m.group(2) for m in re.finditer(r"\n\s*(\w+)\s*\{\s*type\s+(\w+);", txt)}


def _set_patch_types(path: Path, types: dict[str, str]) -> None:
    txt = path.read_text(encoding="utf-8", errors="replace")
    def fix(m):
        name, body = m.group(1), m.group(2)
        if name in types:
            body = re.sub(r"type\s+\w+;", f"type {types[name]};", body, count=1)
            body = re.sub(r"\s*physicalType\s+\w+;", "", body)
        return f"{name}\n    {{{body}}}"
    path.write_text(re.sub(r"(\w+)\s*\n\s*\{([^{}]*)\}", fix, txt), encoding="utf-8", newline="\n")


def compile_conjugate_base(case: dict) -> dict[str, str]:
    h = lambda cls, obj: HEADER.format(cls=cls, obj=obj, cid=case["case_id"], rev=case["revision"])
    from .templates import FLUID_PROPS, MATERIALS_SOLID, SOLID_PROPS
    fluids = [b for b, i in case["bodies"].items() if i["role"] == "fluid"]
    solids = [b for b, i in case["bodies"].items() if i["role"] == "solid"]
    files = {
        "system/controlDict": h("dictionary", "controlDict") + """
application chtMultiRegionSimpleFoam;
startFrom startTime; startTime 0; stopAt endTime; endTime 8000; deltaT 1;
writeControl timeStep; writeInterval 8000; purgeWrite 1;
writeFormat ascii; writePrecision 8; timeFormat general; runTimeModifiable false;
""",
        "system/fvSchemes": h("dictionary", "fvSchemes") + "ddtSchemes {}\ngradSchemes {}\ndivSchemes {}\nlaplacianSchemes {}\ninterpolationSchemes {}\nsnGradSchemes {}\n",
        "system/fvSolution": h("dictionary", "fvSolution") + "SIMPLE {}\n",
        "constant/regionProperties": h("dictionary", "regionProperties") + f"regions\n(\n    fluid ({' '.join(fluids)})\n    solid ({' '.join(solids)})\n);\n",
        "constant/g": h("uniformDimensionedVectorField", "g") + "dimensions [0 1 -2 0 0 0 0];\nvalue (0 0 0);\n",
    }
    for b in fluids:
        fp = FLUID_PROPS[case["bodies"][b]["material"]]
        files[f"constant/{b}/thermophysicalProperties"] = h("dictionary", "thermophysicalProperties") + f"""
thermoType {{ type heRhoThermo; mixture pureMixture; transport const; thermo hConst; equationOfState rhoConst; specie specie; energy sensibleEnthalpy; }}
mixture
{{
    specie {{ molWeight 18; }}
    equationOfState {{ rho {fp['rho']}; }}
    thermodynamics {{ Cp {fp['cp']}; Hf 0; }}
    transport {{ mu {fp['mu']}; Pr {fp['Pr']}; }}
}}
"""
        files[f"constant/{b}/turbulenceProperties"] = h("dictionary", "turbulenceProperties") + "simulationType laminar;\n"
        files[f"system/{b}/fvSchemes"] = h("dictionary", "fvSchemes") + """
ddtSchemes { default steadyState; }
gradSchemes { default Gauss linear; }
divSchemes
{
    default none;
    div(phi,U) bounded Gauss linearUpwind grad(U);
    div(phi,K) bounded Gauss upwind;
    div(phi,h) bounded Gauss upwind;
    div(((rho*nuEff)*dev2(T(grad(U))))) Gauss linear;
}
laplacianSchemes { default Gauss linear limited corrected 0.5; }
interpolationSchemes { default linear; }
snGradSchemes { default limited corrected 0.5; }
"""
        files[f"system/{b}/fvSolution"] = h("dictionary", "fvSolution") + """
solvers
{
    "(rho|rhoFinal)" { solver PCG; preconditioner DIC; tolerance 1e-7; relTol 0; }
    p_rgh { solver GAMG; smoother GaussSeidel; tolerance 1e-7; relTol 0.01; }
    "(U|h)" { solver PBiCGStab; preconditioner DILU; tolerance 1e-8; relTol 0.1; }
}
SIMPLE { momentumPredictor on; nNonOrthogonalCorrectors 1; residualControl { p_rgh 1e-5; U 1e-6; h 1e-7; } }
relaxationFactors { fields { rho 1; p_rgh 0.7; } equations { U 0.5; h 0.9; } }
"""
    for b in solids:
        mat = case["bodies"][b]["material"]
        sp_ = SOLID_PROPS[mat]
        k = units.to_si(MATERIALS_SOLID[mat]["k"])
        files[f"constant/{b}/thermophysicalProperties"] = h("dictionary", "thermophysicalProperties") + f"""
thermoType {{ type heSolidThermo; mixture pureMixture; transport constIso; thermo hConst; equationOfState rhoConst; specie specie; energy sensibleEnthalpy; }}
mixture
{{
    specie {{ molWeight 50; }}
    transport {{ kappa {k}; }}
    thermodynamics {{ Hf 0; Cp {sp_['cp']}; }}
    equationOfState {{ rho {sp_['rho']}; }}
}}
"""
        files[f"system/{b}/fvSchemes"] = h("dictionary", "fvSchemes") + """
ddtSchemes { default steadyState; }
gradSchemes { default Gauss linear; }
divSchemes { default none; }
laplacianSchemes { default none; laplacian(alpha,h) Gauss linear limited corrected 0.5; }
interpolationSchemes { default linear; }
snGradSchemes { default limited corrected 0.5; }
"""
        files[f"system/{b}/fvSolution"] = h("dictionary", "fvSolution") + """
solvers { h { solver PCG; preconditioner DIC; tolerance 1e-8; relTol 0.1; } }
SIMPLE { nNonOrthogonalCorrectors 1; residualControl { h 1e-7; } }
relaxationFactors { equations { h 1; } }
"""
    return files


def conjugate_fields(case: dict, region: str, patches: dict[str, str]) -> dict[str, str]:
    """0/<region>/* written after splitMeshRegions, from the real patch list of that region."""
    h = lambda cls, obj: HEADER.format(cls=cls, obj=obj, cid=case["case_id"], rev=case["revision"])
    fluid = case["bodies"][region]["role"] == "fluid"
    inlets = [b for b in case["boundaries"].values() if b.get("role") == "water-inlet"]
    T0 = units.to_si(inlets[0]["temperature"]) if inlets else 293.15
    out = {}

    def write(name, cls, dims, internal, bc):
        body = "\n".join(f"    {p} {{ {bc(p)} }}" for p in patches)
        out[f"0/{region}/{name}"] = h(cls, name) + f"\ndimensions {dims};\ninternalField {internal};\nboundaryField\n{{\n{body}\n}}\n"

    def role(p):
        return case["boundaries"].get(p, {}).get("role")

    def T_bc(p):
        if "_to_" in p:
            return f"type compressible::turbulentTemperatureCoupledBaffleMixed; Tnbr T; kappaMethod {'fluidThermo' if fluid else 'solidThermo'}; value uniform {T0};"
        r, b = role(p), case["boundaries"].get(p, {})
        if r == "water-inlet":
            return f"type fixedValue; value uniform {units.to_si(b['temperature'])};"
        if r == "water-outlet":
            return f"type inletOutlet; inletValue uniform {T0}; value uniform {T0};"
        if r == "temperature":
            return f"type fixedValue; value uniform {units.to_si(b['temperature'])};"
        if r == "heat-flux":
            return f"type externalWallHeatFluxTemperature; mode flux; q uniform {units.to_si(b['flux'])}; kappaMethod solidThermo; value uniform {T0};"
        if r == "convection":
            return (f"type externalWallHeatFluxTemperature; mode coefficient; h uniform {units.to_si(b['h'])}; "
                    f"Ta constant {units.to_si(b['tinf'])}; kappaMethod solidThermo; value uniform {T0};")
        return f"type zeroGradient; value uniform {T0};"

    write("T", "volScalarField", "[0 0 0 1 0 0 0]", f"uniform {T0}", T_bc)
    write("p", "volScalarField", "[1 -1 -2 0 0 0 0]", "uniform 1e5", lambda p: "type calculated; value uniform 1e5;")
    if fluid:
        def U_bc(p):
            r, b = role(p), case["boundaries"].get(p, {})
            if r == "water-inlet":
                return f"type surfaceNormalFixedValue; refValue uniform {-units.to_si(b['speed'])}; value uniform (0 0 0);"
            if r == "water-outlet":
                return "type inletOutlet; inletValue uniform (0 0 0); value uniform (0 0 0);"
            return "type noSlip;"
        write("U", "volVectorField", "[0 1 -1 0 0 0 0]", "uniform (0 0 0)", U_bc)
        write("p_rgh", "volScalarField", "[1 -1 -2 0 0 0 0]", "uniform 1e5",
              lambda p: "type fixedValue; value uniform 1e5;" if role(p) == "water-outlet" else "type fixedFluxPressure; value uniform 1e5;")
    return out


def run_conjugate(case: dict, jd: Path, prog, proc) -> dict:
    from scipy.spatial import cKDTree
    from .config import find_openfoam, openfoam_env
    from .fem_tet10 import tri_areas
    from .geometry import mesh_dir
    from .run_worker import _mesh_for_run
    from .templates import FLUID_PROPS
    foam = find_openfoam()
    if not foam:
        raise RuntimeError("OpenFOAM is not installed")
    mesh = _mesh_for_run(case, jd, prog)
    wd = foam_workdir(jd)
    for rel, text in compile_conjugate_base(case).items():
        p = wd / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    (wd / "mesh.msh").write_bytes((mesh_dir(case) / "mesh.msh").read_bytes())
    env = openfoam_env(foam)
    exe = lambda n: str(Path(foam["bin"]) / f"{n}.exe")
    prog("job.meshing", 0.06)
    if proc([exe("gmshToFoam"), "-case", str(wd), str(wd / "mesh.msh")], wd, wd / "log.gmshToFoam", jd, env) != 0:
        raise RuntimeError("gmshToFoam failed: see log.gmshToFoam")
    if proc([exe("splitMeshRegions"), "-case", str(wd), "-cellZones", "-overwrite"], wd, wd / "log.split", jd, env) != 0:
        raise RuntimeError("splitMeshRegions failed: see log.split")
    regions = list(case["bodies"])
    for r in regions:
        bf = wd / "constant" / r / "polyMesh" / "boundary"
        patches = _boundary_patches(bf)
        fluid = case["bodies"][r]["role"] == "fluid"
        types = {p: "wall" for p, t in patches.items() if t == "patch" and
                 case["boundaries"].get(p, {}).get("role") not in ("water-inlet", "water-outlet")}
        _set_patch_types(bf, types)
        for rel, text in conjugate_fields(case, r, patches).items():
            q = wd / rel
            q.parent.mkdir(parents=True, exist_ok=True)
            q.write_text(text, encoding="utf-8", newline="\n")
    prog("job.solving", 0.15)
    if proc([exe("chtMultiRegionSimpleFoam"), "-case", str(wd)], wd, wd / "log.cht", jd, env) != 0:
        tail = (wd / "log.cht").read_text(errors="replace").strip().splitlines()[-5:]
        raise RuntimeError("chtMultiRegionSimpleFoam failed: " + " | ".join(tail))
    prog("job.post", 0.9)
    times = sorted((x for x in wd.iterdir() if x.is_dir() and re.fullmatch(r"[0-9.eE+-]+", x.name) and x.name != "0"),
                   key=lambda x: float(x.name))
    last = times[-1]
    nodes, tets, tbody = mesh["nodes"], mesh["tets"][:, :4], mesh["tet_body"]
    Tt = np.full(len(tets), np.nan); Ut = np.zeros((len(tets), 3))
    for r in regions:
        proc([exe("postProcess"), "-case", str(wd), "-region", r, "-func", "writeCellCentres", "-latestTime"],
             wd, wd / f"log.post.{r}", jd, env)
        T = _internal(last / r / "T", False); C = _internal(last / r / "C", True)
        sel = np.where(tbody == int(r[1:]))[0]
        _, idx = cKDTree(C).query(nodes[tets[sel]].mean(axis=1))
        Tt[sel] = T[idx]
        if case["bodies"][r]["role"] == "fluid":
            Ut[sel] = _internal(last / r / "U", True)[idx]
    acc = np.zeros((len(nodes), 4)); cnt = np.zeros(len(nodes))
    for c in range(4):
        np.add.at(acc, tets[:, c], np.column_stack([Tt, Ut]))
        np.add.at(cnt, tets[:, c], 1)
    nodal = acc / np.maximum(cnt, 1)[:, None]
    np.savez_compressed(jd / "results.npz", T=nodal[:, 0], U=nodal[:, 1:])
    # heat balance: heat put in through the solid surfaces vs heat carried away by the water
    q_in = 0.0
    for key, b in case["boundaries"].items():
        tri = mesh.get(f"face_{key}")
        if tri is not None and b.get("role") == "heat-flux":
            q_in += units.to_si(b["flux"]) * tri_areas(nodes, tri).sum()
    t_out, m_dot, t_in, cp = [], 0.0, None, None
    for key, b in case["boundaries"].items():
        tri = mesh.get(f"face_{key}")
        if tri is None:
            continue
        body = next((f["bodies"][0] for f in case["geometry"]["faces"] if f["key"] == key), None)
        if b.get("role") == "water-inlet":
            fp = FLUID_PROPS[case["bodies"][body]["material"]]
            cp = fp["cp"]
            m_dot += fp["rho"] * units.to_si(b["speed"]) * tri_areas(nodes, tri).sum()
            t_in = units.to_si(b["temperature"])
        elif b.get("role") == "water-outlet":
            # flow-weighted mean over the fluid cells touching the outlet (nodal values would mix in the hot solid)
            fl = np.where(np.isin(tbody, [int(body[1:])]))[0]
            owner = {}
            for e in fl:
                tt = tets[e]
                for a_, b_, c_ in ((0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)):
                    owner[tuple(sorted((tt[a_], tt[b_], tt[c_])))] = e
            cells = np.array([owner[tuple(sorted(r[:3]))] for r in tri])
            P = nodes[tri[:, :3]]
            nvec = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]) / 2          # area-weighted normal
            cen = nodes[tets[cells]].mean(axis=1)
            nvec *= np.sign(np.einsum("ij,ij->i", nvec, P[:, 0] - cen))[:, None]  # outward
            qn = np.clip(np.einsum("ij,ij->i", Ut[cells], nvec), 0, None)
            t_out.append(float((Tt[cells] * qn).sum() / qn.sum()) if qn.sum() > 0 else float(np.mean(Tt[cells])))
    t_outlet = float(np.mean(t_out)) if t_out else float("nan")
    q_water = m_dot * cp * (t_outlet - t_in) if cp and t_in is not None else float("nan")
    solid_nodes = np.unique(tets[np.isin(tbody, [int(r[1:]) for r in regions if case["bodies"][r]["role"] == "solid"])])
    log = (wd / "log.cht").read_text(errors="replace")
    resid = [float(x) for x in re.findall(r"Solving for h, Initial residual = ([0-9.eE+-]+)", log)]
    balance = abs(q_water - q_in) / q_in if q_in > 0 else float("nan")
    metrics = {"t_solid_max_k": float(nodal[solid_nodes, 0].max()), "t_outlet_k": t_outlet, "t_inlet_k": t_in,
               "q_in_w": q_in, "q_water_w": q_water, "heat_balance": balance, "mass_flow_kgs": m_dot,
               "residual": resid[-1] if resid else 1.0, "nodes": int(len(nodes)), "elements": int(len(tets))}
    converged = bool(np.isfinite(t_outlet) and (q_in == 0 or balance < 0.05))
    return {"kind": "conjugate", "metrics": metrics, "converged": converged,
            "converged_detail": {"heat_balance": balance, "limit": 0.05,
                                 "note": "heat carried away by the water vs heat put in (ignores surface cooling)"},
            "reference": {"applicable": False, "why": "no analytic reference for this shape"}}


# ------------------------------------------------------------------ external flow with snappyHexMesh (hex + wall layers)

SNAPPY_LEVELS = {"coarse": (3, 4), "normal": (4, 5), "fine": (5, 6)}


def read_vtk_polydata(path: Path) -> dict:
    """Minimal legacy-ASCII VTK POLYDATA reader (points, polygons, point fields)."""
    tok = path.read_text(encoding="utf-8", errors="replace").split()
    i, out, pts, polys, fields, npts = 0, {}, None, [], {}, 0
    while i < len(tok):
        w = tok[i].upper()
        if w == "POINTS":
            npts = int(tok[i + 1]); pts = np.array(tok[i + 3:i + 3 + 3 * npts], float).reshape(-1, 3); i += 3 + 3 * npts
        elif w == "POLYGONS":
            n, size = int(tok[i + 1]), int(tok[i + 2]); j = i + 3
            if tok[j].upper() == "OFFSETS":          # VTK 5.1 layout
                no = n; offs = np.array(tok[j + 2:j + 2 + no], int); j += 2 + no
                conn = np.array(tok[j + 2:j + 2 + offs[-1]], int); j += 2 + offs[-1]
                polys = [conn[offs[k]:offs[k + 1]] for k in range(no - 1)]
                i = j
            else:
                for _ in range(n):
                    k = int(tok[j]); polys.append(np.array(tok[j + 1:j + 1 + k], int)); j += 1 + k
                i = j
        elif w == "FIELD":
            nf = int(tok[i + 2]); j = i + 3
            for _ in range(nf):
                name, nc, nt = tok[j], int(tok[j + 1]), int(tok[j + 2])
                fields[name] = np.array(tok[j + 4:j + 4 + nc * nt], float).reshape(nt, nc); j += 4 + nc * nt
            i = j
        elif w in ("SCALARS", "VECTORS"):
            name = tok[i + 1]; nc = 1 if w == "SCALARS" else 3; j = i + 3
            if w == "SCALARS" and tok[j].isdigit():
                nc = int(tok[j]); j += 1
            if tok[j].upper() == "LOOKUP_TABLE":
                j += 2
            fields[name] = np.array(tok[j:j + nc * npts], float).reshape(npts, nc); i = j + nc * npts
        else:
            i += 1
    tris = []
    for p in polys:
        for k in range(1, len(p) - 1):
            tris.append([p[0], p[k], p[k + 1]])
    return {"points": pts, "tris": np.array(tris, int), "fields": fields}


def run_external_snappy(case: dict, jd: Path, prog, proc) -> dict:
    from . import geometry
    from .config import find_openfoam, openfoam_env
    foam = find_openfoam()
    if not foam:
        raise RuntimeError("OpenFOAM is not installed")
    (b0, b1) = [np.array(v, float) for v in case["geometry"]["bbox"]]
    L = float((b1 - b0).max())
    dm = geometry.external_domain(case)
    axis, sign = dm["axis"], dm["sign"]
    lo, hi = b0 - dm["side"] * L, b1 + dm["side"] * L
    if sign > 0:
        lo[axis] = b0[axis] - dm["up"] * L; hi[axis] = b1[axis] + dm["down"] * L
    else:
        hi[axis] = b1[axis] + dm["up"] * L; lo[axis] = b0[axis] - dm["down"] * L
    wd = foam_workdir(jd)
    (wd / "constant" / "triSurface").mkdir(parents=True, exist_ok=True)
    prog("job.meshing", 0.03)
    stl = wd / "constant" / "triSurface" / "body.stl"
    geometry._run_worker(geometry.worker_job(case, size="fine", volume=False, order=1, out=str(jd / "surf"),
                                             stl=str(stl), h=L / 60), timeout=600)
    # body surface for frontal area and the drag reference
    import struct
    tri_pts = _read_stl(stl)
    nodes = tri_pts.reshape(-1, 3)
    d = np.array(DIRS[case["flow"]["direction"]], float)
    aref = frontal_area(nodes, np.arange(len(nodes)).reshape(-1, 3), d)
    lref = math.sqrt(4 * aref / math.pi)
    center = (b0 + b1) / 2
    lv = SNAPPY_LEVELS[case["mesh"]["size"]]
    d0 = L / 2.0                                              # background cell size (level 0)
    n = np.maximum(np.ceil((hi - lo) / d0).astype(int), 4)
    h = lambda cls, obj: HEADER.format(cls=cls, obj=obj, cid=case["case_id"], rev=case["revision"])
    v = lambda p: f"({p[0]:.9g} {p[1]:.9g} {p[2]:.9g})"
    X0, Y0, Z0 = lo; X1, Y1, Z1 = hi
    verts = [(X0, Y0, Z0), (X1, Y0, Z0), (X1, Y1, Z0), (X0, Y1, Z0), (X0, Y0, Z1), (X1, Y0, Z1), (X1, Y1, Z1), (X0, Y1, Z1)]
    faces = {("x", 0): "(0 4 7 3)", ("x", 1): "(1 2 6 5)", ("y", 0): "(0 1 5 4)", ("y", 1): "(3 7 6 2)",
             ("z", 0): "(0 3 2 1)", ("z", 1): "(4 5 6 7)"}
    ax = "xyz"[axis]
    inlet_side, outlet_side = (0, 1) if sign > 0 else (1, 0)
    sides = [f for (a, s), f in faces.items() if a != ax]
    files = {
        "system/blockMeshDict": h("dictionary", "blockMeshDict") + "scale 1;\nvertices\n(\n" +
        "\n".join(f"    {v(p)}" for p in verts) + f"\n);\nblocks\n(\n    hex (0 1 2 3 4 5 6 7) ({n[0]} {n[1]} {n[2]}) simpleGrading (1 1 1)\n);\n"
        f"boundary\n(\n    inlet {{ type patch; faces ({faces[(ax, inlet_side)]}); }}\n"
        f"    outlet {{ type patch; faces ({faces[(ax, outlet_side)]}); }}\n"
        f"    sides {{ type patch; faces ({' '.join(sides)}); }}\n);\n",
        "system/surfaceFeatureExtractDict": h("dictionary", "surfaceFeatureExtractDict") +
        "body.stl\n{\n    extractionMethod extractFromSurface;\n    extractFromSurfaceCoeffs { includedAngle 150; }\n    writeObj no;\n}\n",
        "system/meshQualityDict": h("dictionary", "meshQualityDict") + "#includeEtc \"caseDicts/meshQualityDict\"\nminFaceWeight 0.02;\n",
    }
    near_lo, near_hi = b0 - 0.5 * L, b1 + 0.5 * L
    wake_lo, wake_hi = b0 - 0.6 * L, b1 + 0.6 * L
    if sign > 0:
        wake_hi[axis] = b1[axis] + 4 * L
    else:
        wake_lo[axis] = b0[axis] - 4 * L
    inside = lo + 0.0731 * (hi - lo) + np.array([1.3e-4, 1.7e-4, 1.1e-4]) * L    # a point in the fluid, away from the body
    files["system/snappyHexMeshDict"] = h("dictionary", "snappyHexMeshDict") + f"""
castellatedMesh true; snap true; addLayers true;
geometry
{{
    body.stl {{ type triSurfaceMesh; name body; }}
    nearBox {{ type box; min {v(near_lo)}; max {v(near_hi)}; }}
    wakeBox {{ type box; min {v(wake_lo)}; max {v(wake_hi)}; }}
}}
castellatedMeshControls
{{
    maxLocalCells 2000000; maxGlobalCells 4000000; minRefinementCells 0; maxLoadUnbalance 0.1;
    nCellsBetweenLevels 3;
    features ( {{ file "body.eMesh"; level {lv[1]}; }} );
    refinementSurfaces {{ body {{ level ({lv[0]} {lv[1]}); patchInfo {{ type wall; }} }} }}
    resolveFeatureAngle 30;
    refinementRegions
    {{
        nearBox {{ mode inside; levels ((1e15 {lv[0] - 1})); }}
        wakeBox {{ mode inside; levels ((1e15 {max(lv[0] - 2, 1)})); }}
    }}
    locationInMesh {v(inside)};
    allowFreeStandingZoneFaces true;
}}
snapControls {{ nSmoothPatch 3; tolerance 2.0; nSolveIter 50; nRelaxIter 5; nFeatureSnapIter 10;
               implicitFeatureSnap false; explicitFeatureSnap true; multiRegionFeatureSnap false; }}
addLayersControls
{{
    relativeSizes true;
    layers {{ body {{ nSurfaceLayers 3; }} }}
    expansionRatio 1.2; finalLayerThickness 0.5; minThickness 0.1; nGrow 0;
    featureAngle 120; slipFeatureAngle 30; nRelaxIter 5; nSmoothSurfaceNormals 1; nSmoothNormals 3;
    nSmoothThickness 10; maxFaceThicknessRatio 0.5; maxThicknessToMedialRatio 0.3; minMedialAxisAngle 90;
    nBufferCellsNoExtrude 0; nLayerIter 50;
}}
meshQualityControls {{ #include "meshQualityDict" nSmoothScale 4; errorReduction 0.75; }}
mergeTolerance 1e-6;
"""
    lift = np.array([0, 0, 1.0]) if abs(d[2]) < 0.9 else np.array([0, 1.0, 0])
    plane_n = lift
    surfaces = f"""
    samples
    {{
        type surfaces; libs (sampling); writeControl onEnd; surfaceFormat vtk;
        formatOptions {{ vtk {{ legacy true; format ascii; }} }}
        fields (p U); interpolationScheme cellPoint;
        surfaces
        {{
            plane {{ type cuttingPlane; point {v(center)}; normal {v(plane_n)}; interpolate true; }}
            body {{ type patch; patches (body); interpolate true; }}
        }}
    }}"""
    for rel, text in {**files, **compile_external(case, aref, lref, center, surfaces)}.items():
        p = wd / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    meta = json.loads((wd / "meta.json").read_text())
    env = openfoam_env(foam)
    exe = lambda nme: str(Path(foam["bin"]) / f"{nme}.exe")
    for step, frac in (("blockMesh", 0.05), ("surfaceFeatureExtract", 0.06), ("snappyHexMesh", 0.07)):
        prog("job.meshing", frac)
        args = [exe(step), "-case", str(wd)] + (["-overwrite"] if step == "snappyHexMesh" else [])
        if proc(args, wd, wd / f"log.{step}", jd, env) != 0:
            tail = (wd / f"log.{step}").read_text(errors="replace").strip().splitlines()[-3:]
            raise RuntimeError(f"{step} failed: " + " | ".join(tail))
    proc([exe("checkMesh"), "-case", str(wd)], wd, wd / "log.checkMesh", jd, env)
    cm = (wd / "log.checkMesh").read_text(errors="replace")
    m_cells = re.search(r"\n\s*cells:\s+(\d+)", cm)
    ncells = int(m_cells.group(1)) if m_cells else 0
    prog("job.solving", 0.15)
    if proc([exe("simpleFoam"), "-case", str(wd)], wd, wd / "log.simpleFoam", jd, env) != 0:
        tail = (wd / "log.simpleFoam").read_text(errors="replace").strip().splitlines()[-4:]
        raise RuntimeError("simpleFoam failed: " + " | ".join(tail))
    prog("job.post", 0.92)
    rho = units.to_si(case["materials"]["fluid"].get("rho", {"value": 1000, "unit": "kg/m3"}))
    vt = {p.stem: p for p in wd.glob("postProcessing/samples/*/*.vtk")}
    store_ = {}
    if "plane" in vt:
        pl = read_vtk_polydata(vt["plane"])
        store_.update(plane_P=pl["points"], plane_T=pl["tris"], plane_U=pl["fields"].get("U", np.zeros((len(pl["points"]), 3))))
    if "body" in vt:
        bd = read_vtk_polydata(vt["body"])
        store_.update(body_P=bd["points"], body_T=bd["tris"], body_p=bd["fields"].get("p", np.zeros((len(bd["points"]), 1)))[:, 0] * rho)
    np.savez_compressed(jd / "results.npz", snappy=1, **store_)
    co = _read_coefficients(wd) or {}
    cd_hist = co.get("Cd", np.array([np.nan])); cl_hist = co.get("Cl", np.array([np.nan]))
    tail = cd_hist[-max(10, len(cd_hist) // 10):]
    cd, cl = float(cd_hist[-1]), float(cl_hist[-1])
    cd_var = float(np.ptp(tail) / abs(np.mean(tail))) if len(tail) > 1 and np.mean(tail) else 1.0
    log = (wd / "log.simpleFoam").read_text(errors="replace")
    resid = [float(x) for x in re.findall(r"Solving for Ux, Initial residual = ([0-9.eE+-]+)", log)]
    Uinf = meta["U"]
    speed = np.linalg.norm(store_.get("plane_U", np.zeros((1, 3))), axis=1)
    metrics = {"cd": cd, "cl": cl, "drag_n": 0.5 * rho * Uinf ** 2 * aref * cd, "re": meta["re"], "aref_m2": aref,
               "lref_m": lref, "turbulent": meta["turbulent"], "cd_variation": cd_var, "residual": resid[-1] if resid else 1.0,
               "max_speed": float(speed.max()), "iterations": len(resid), "nodes": ncells, "elements": ncells,
               "mesher": "snappyHexMesh"}
    converged = bool(cd_var < 0.01 and np.isfinite(cd))
    ref = {"applicable": False, "why": "no analytic reference for this shape"}
    if case["template"] == "sphere-drag":
        if 1 <= meta["re"] <= 800 and not meta["turbulent"]:
            cref = schiller_naumann(meta["re"])
            err = (cd - cref) / cref * 100
            ref = {"applicable": True, "quantity": "cd", "reference": cref, "computed": cd, "unit": "-", "error_pct": err,
                   "tolerance_pct": case["reference"]["tolerance_pct"], "pass": abs(err) <= case["reference"]["tolerance_pct"],
                   "metric": "Schiller-Naumann: Cd = 24/Re (1 + 0.15 Re^0.687)"}
        else:
            ref = {"applicable": False, "why": "the Schiller-Naumann comparison is for steady laminar flow (Re <= 300 here)"}
    return {"kind": "external", "metrics": metrics, "converged": converged,
            "converged_detail": {"cd_variation_last10pct": cd_var, "limit": 0.01}, "reference": ref}


def _read_stl(path: Path) -> np.ndarray:
    """Triangles (n,3,3) from an ASCII or binary STL."""
    raw = path.read_bytes()
    if raw[:5] == b"solid" and b"facet" in raw[:1000]:
        v = re.findall(rb"vertex\s+([-0-9.eE+]+)\s+([-0-9.eE+]+)\s+([-0-9.eE+]+)", raw)
        return np.array(v, float).reshape(-1, 3, 3)
    n = int.from_bytes(raw[80:84], "little")
    a = np.frombuffer(raw[84:84 + 50 * n], dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    return a["v"].astype(float)
