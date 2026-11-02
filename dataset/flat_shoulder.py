"""Family 7: a flat bar stepping from width D down to d with shoulder fillets of radius r, thickness t, in tension.

Reference: Peterson's opposite-shoulder-fillet curve fit (as given by amesweb.info's calculator, not checked against the
book), for thin bars: a trend check, not a certificate. The certificate is the mesh study and CalculiX.
One eighth is solved: symmetry on x = 0 (width), y = 0 (mid-thickness) and z = 0 (the end of the narrow part, as if the
bar continued mirror-wise); the end of the wide part is pulled. Lengths are scaled by d (d = 20 mm in the solves)."""
from __future__ import annotations

import math
from pathlib import Path

D_SMALL = 20.0                # mm
LS_OVER_d = 1.5               # narrow length / d (fillet end to the symmetry plane)
LL_OVER_D = 1.5               # wide length / D
F = 1000.0                    # N on the eighth
E = 200e9

PARAMS = {
    "D_over_d": (1.2, 2.0),
    "r_over_h": (0.2, 0.9),        # fillet radius / step height, as in the stepped shaft
    "t_over_d": (0.1, 1.0),        # thickness / narrow width (thin: plane stress; thick: the 3D effect shows)
    "nu": (0.25, 0.35),
}
EXPECTED_DIRECTIONS = {"kt": {"r_over_h": -1}}
QUANTITIES = ("kt",)
NORMALISED = {"kt": "kt_over_peterson"}
CHECK_EQUILIBRIUM = False      # the load is carried by a symmetry plane, not a fixed face
MESH_SIZE = "normal"           # see stepped_shaft.py
DEPTHS = (0.005, 0.01)         # probe depths / r; the surface value is extrapolated linearly from the two
VIEW = (35, -125)              # picture.py: the fillet faces the camera
PICTURE_CROP = 0.2


def dims(p: dict, scale: float = 1.0) -> dict:
    d = D_SMALL * scale
    D = p["D_over_d"] * d
    return {"d": d, "D": D, "r": p["r_over_h"] * (D - d) / 2, "t": p["t_over_d"] * d, "Ls": LS_OVER_d * d,
            "Ll": LL_OVER_D * D}


def write_step(p: dict, path: Path, scale: float = 1.0) -> None:
    """The profile in the x-z plane, extruded through half the thickness (a single solid: no split symmetry faces)."""
    import gmsh
    g = dims(p, scale)
    hd, hD, r, Ls, Ll = g["d"] / 2, g["D"] / 2, g["r"], g["Ls"], g["Ll"]
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("flat")
        occ = gmsh.model.occ
        pts = [occ.addPoint(x, 0, z) for x, z in ((0, 0), (hd, 0), (hd, Ls - r), (hd + r, Ls), (hD, Ls), (hD, Ls + Ll), (0, Ls + Ll))]
        centre = occ.addPoint(hd + r, 0, Ls - r)
        cur = [occ.addLine(pts[0], pts[1]), occ.addLine(pts[1], pts[2]), occ.addCircleArc(pts[2], centre, pts[3]),
               occ.addLine(pts[3], pts[4]), occ.addLine(pts[4], pts[5]), occ.addLine(pts[5], pts[6]), occ.addLine(pts[6], pts[0])]
        surf = occ.addPlaneSurface([occ.addCurveLoop(cur)])
        occ.extrude([(2, surf)], 0, g["t"] / 2, 0)
        occ.remove([(0, centre)])
        occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()


def refine_face(faces: list[dict]) -> str:
    cyl = [f["key"] for f in faces if f.get("type") == "Cylinder"]
    assert len(cyl) == 1, [(f["key"], f.get("type")) for f in faces]
    return cyl[0]


def refine_length(p: dict, scale: float = 1.0) -> float:
    return dims(p, scale)["r"]


def boundary_changes(faces: list[dict], p: dict, scale: float = 1.0, force: float = F) -> dict:
    g = dims(p, scale)
    tol = 1e-3 * g["d"]
    def plane(axis, value, sign):
        return [f["key"] for f in faces if f.get("normal") and sign * f["normal"][axis] > 0.99
                and abs(f["centroid_mm"][axis] - value) < tol]
    sym = plane(0, 0, -1) + plane(1, 0, -1) + plane(2, 0, -1)
    end = plane(2, g["Ls"] + g["Ll"], 1)
    assert len(sym) == 3 and len(end) == 1, (sym, end)
    ch = {f"boundaries.{k}.role": "symmetry" for k in sym}
    ch.update({f"boundaries.{end[0]}.role": "load", f"boundaries.{end[0]}.force": f"{force} N",
               f"boundaries.{end[0]}.direction": "+z"})
    return ch


def fillet_arc(p: dict, scale: float, y: float, depth: float, n: int = 61) -> list[list[float]]:
    """Points on the fillet at height y, from where it meets the narrow part (0 deg) to the shoulder (90 deg),
    depth x r inside the material."""
    g = dims(p, scale)
    cx, cz, R = g["d"] / 2 + g["r"], g["Ls"] - g["r"], g["r"] * (1 + depth)
    return [[cx - R * math.cos(math.radians(90 * i / (n - 1))), y, cz + R * math.sin(math.radians(90 * i / (n - 1)))]
            for i in range(n)]


def measure(C, cid: str, p: dict, scale: float, refine_key: str) -> dict:
    """Peak first principal stress along the fillet at the mid-thickness and near the free face, each extrapolated to
    the surface. The answer is the mid-thickness value (as in the plate with a hole)."""
    g = dims(p, scale)
    ys = (0.0, 0.25 * g["t"], 0.49 * g["t"])
    arcs = [fillet_arc(p, scale, y, dp) for y in ys for dp in DEPTHS]
    pr = C.probe_results(cid, [q for arc in arcs for q in arc], None, [refine_key], None, "en", 1, None)
    s1 = [pt["values"]["s1"] for pt in pr["points"]]
    n = len(arcs[0])
    w = DEPTHS[0] / (DEPTHS[1] - DEPTHS[0])
    surf = []
    for j in range(len(ys)):
        a1, a2 = s1[2 * j * n:(2 * j + 1) * n], s1[(2 * j + 1) * n:(2 * j + 2) * n]
        surf.append([x + w * (x - y) for x, y in zip(a1, a2)])
    k = max(range(n), key=surf[0].__getitem__)
    end = [[g["D"] / 2 * f, g["t"] / 2 * h, g["Ls"] + g["Ll"]] for f in (0.1, 0.5, 0.9) for h in (0.0, 0.5, 1.0)]
    uz = [pt["values"]["uz"] for pt in C.probe_results(cid, end, None, None, None, "en", 1, None)["points"]]
    return {"fillet_s1_mpa": surf[0][k], "fillet_s1_max_mpa": max(max(a) for a in surf),
            "fillet_deg": round(90 * k / (n - 1), 1), "arc_inside": sum(pt["inside"] for pt in pr["points"]) / len(pr["points"]),
            "end_uz_mm": sum(uz) / len(uz), "end_uz_spread": max(uz) - min(uz)}


def nondim(s: dict, p: dict, scale: float = 1.0, force: float = F) -> dict:
    g = dims(p, scale)
    nominal = force / (g["d"] / 2 * g["t"] / 2)                    # the eighth's force over its share of the narrow section
    return {"kt": s["fillet_s1_mpa"] / nominal}


def peterson_kt(p: dict) -> float:
    """Opposite shoulder fillets, tension, thin bar: Kt = C1 + C2 x + C3 x^2 + C4 x^3 with x = 2h / D."""
    h_r = 1 / p["r_over_h"]
    s = math.sqrt(h_r)
    if h_r <= 2.0:
        c = (1.006 + 1.008 * s - 0.044 * h_r, -0.115 - 0.584 * s + 0.315 * h_r,
             0.245 - 1.006 * s - 0.257 * h_r, -0.135 + 0.582 * s - 0.017 * h_r)
    else:
        c = (1.020 + 1.009 * s - 0.048 * h_r, -0.065 - 0.165 * s - 0.007 * h_r,
             -3.459 + 1.266 * s - 0.016 * h_r, 3.505 - 2.109 * s + 0.069 * h_r)
    x = (p["D_over_d"] - 1) / p["D_over_d"]
    return c[0] + c[1] * x + c[2] * x ** 2 + c[3] * x ** 3


def references(p: dict, s: dict, nd: dict) -> dict:
    return {"kt_over_peterson": nd["kt"] / peterson_kt(p), "kt_peak_over_mid": s["fillet_s1_max_mpa"] / s["fillet_s1_mpa"],
            "peak_angle_deg": s["fillet_deg"]}


def mirror_err(s: dict) -> float:
    """No mirror pair (the symmetry is imposed): the spread of the end displacement over the face instead."""
    return abs(s["end_uz_spread"]) / max(abs(s["end_uz_mm"]), 1e-30)
