"""Family 6: a round bar of diameter D with a U-shaped circumferential groove (bottom radius r, minimum diameter d), in
tension.

Reference: Peterson's U-groove curve fit (as given by amesweb.info's calculator, not checked against the book), a trend
check only, not a certificate. The certificate is the mesh study, CalculiX and the axisymmetry check.
A quarter is solved (symmetry on x = 0 and y = 0) and half the length: the groove's mid-plane z = 0 is a symmetry plane,
the far end is pulled. Lengths are scaled by d (d = 20 mm in the solves)."""
from __future__ import annotations

import math
from pathlib import Path

D_MIN = 20.0                  # mm
LH_OVER_D = 2.0               # half length / D
F = 1000.0                    # N on the quarter
E = 200e9

# As in the stepped shaft, r is a fraction of the groove depth h = (D - d) / 2, so every point has a U with straight
# walls. Above about 0.85 the wall is a sliver that the mesher struggles with.
PARAMS = {
    "D_over_d": (1.2, 2.0),
    "r_over_h": (0.25, 0.85),
    "nu": (0.25, 0.35),
}
EXPECTED_DIRECTIONS = {"kt": {"r_over_h": -1, "nu": 0}}
QUANTITIES = ("kt",)
NORMALISED = {"kt": "kt_over_peterson"}
MIRROR_BOUNDS = ("kt",)        # the two meridian planes measure kt twice: their gap bounds its error
CHECK_EQUILIBRIUM = False      # the load is carried by a symmetry plane, not a fixed face
MESH_SIZE = "normal"           # see stepped_shaft.py
DEPTHS = (0.005, 0.01)         # probe depths / r; the surface value is extrapolated linearly from the two
VIEW = (24, 122)               # picture.py: the groove faces the camera
PICTURE_CROP = 0.22


def dims(p: dict, scale: float = 1.0) -> dict:
    d = D_MIN * scale
    D = p["D_over_d"] * d
    return {"d": d, "D": D, "r": p["r_over_h"] * (D - d) / 2, "Lh": LH_OVER_D * D}


def write_step(p: dict, path: Path, scale: float = 1.0) -> None:
    """The half profile in the x-z plane, revolved a quarter turn about z."""
    import gmsh
    g = dims(p, scale)
    rd, rD, r, Lh = g["d"] / 2, g["D"] / 2, g["r"], g["Lh"]
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("groove")
        occ = gmsh.model.occ
        pts = [occ.addPoint(x, 0, z) for x, z in ((0, 0), (rd, 0), (rd + r, r), (rD, r), (rD, Lh), (0, Lh))]
        centre = occ.addPoint(rd + r, 0, 0)
        cur = [occ.addLine(pts[0], pts[1]), occ.addCircleArc(pts[1], centre, pts[2]), occ.addLine(pts[2], pts[3]),
               occ.addLine(pts[3], pts[4]), occ.addLine(pts[4], pts[5]), occ.addLine(pts[5], pts[0])]
        surf = occ.addPlaneSurface([occ.addCurveLoop(cur)])
        occ.revolve([(2, surf)], 0, 0, 0, 0, 0, 1, math.pi / 2)
        occ.remove([(0, centre)])
        occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()


def refine_face(faces: list[dict]) -> str:
    tor = [f["key"] for f in faces if f.get("type") == "Torus"]
    assert len(tor) == 1, [(f["key"], f.get("type")) for f in faces]
    return tor[0]


def refine_length(p: dict, scale: float = 1.0) -> float:
    return dims(p, scale)["r"]


def boundary_changes(faces: list[dict], p: dict, scale: float = 1.0, force: float = F) -> dict:
    g = dims(p, scale)
    tol = 1e-3 * g["d"]
    def plane(axis, value, sign):
        return [f["key"] for f in faces if f.get("normal") and sign * f["normal"][axis] > 0.99
                and abs(f["centroid_mm"][axis] - value) < tol]
    sym = plane(0, 0, -1) + plane(1, 0, -1) + plane(2, 0, -1)
    end = plane(2, g["Lh"], 1)
    assert len(sym) == 3 and len(end) == 1, (sym, end)
    ch = {f"boundaries.{k}.role": "symmetry" for k in sym}
    ch.update({f"boundaries.{end[0]}.role": "load", f"boundaries.{end[0]}.force": f"{force} N",
               f"boundaries.{end[0]}.direction": "+z"})
    return ch


def groove_arc(p: dict, scale: float = 1.0, phi_deg: float = 45.0, depth: float = 0.005,
               n: int = 61) -> list[list[float]]:
    """Points along the groove bottom in the meridian plane at phi, from the mid-plane (0 deg) to where the wall starts
    (90 deg), depth x r inside the material."""
    g = dims(p, scale)
    c, R = g["d"] / 2 + g["r"], g["r"] * (1 + depth)
    ph = math.radians(phi_deg)
    out = []
    for i in range(n):
        a = math.radians(90 * i / (n - 1))
        rho, z = c - R * math.cos(a), R * math.sin(a)
        out.append([rho * math.cos(ph), rho * math.sin(ph), z])
    return out


def measure(C, cid: str, p: dict, scale: float, refine_key: str) -> dict:
    """Peak first principal stress along the groove in two meridian planes, extrapolated to the surface."""
    arcs = [groove_arc(p, scale, phi, dp) for phi in (20.0, 70.0) for dp in DEPTHS]
    pr = C.probe_results(cid, [q for arc in arcs for q in arc], None, [refine_key], None, "en", 1, None)
    s1 = [pt["values"]["s1"] for pt in pr["points"]]
    n = len(arcs[0])
    a1, a2, b1, b2 = (s1[i * n:(i + 1) * n] for i in range(4))
    w = DEPTHS[0] / (DEPTHS[1] - DEPTHS[0])
    a = [x + w * (x - y) for x, y in zip(a1, a2)]
    b = [x + w * (x - y) for x, y in zip(b1, b2)]
    k = max(range(n), key=a.__getitem__)
    return {"groove_s1_mpa": a[k], "groove_s1_other_mpa": max(b), "groove_s1_probe_mpa": a1[k],
            "groove_deg": round(90 * k / (n - 1), 1),
            "arc_inside": sum(pt["inside"] for pt in pr["points"]) / len(pr["points"])}


def nondim(s: dict, p: dict, scale: float = 1.0, force: float = F) -> dict:
    g = dims(p, scale)
    nominal = force / (math.pi * g["d"] ** 2 / 16)                 # quarter force over a quarter of the small section
    return {"kt": s["groove_s1_mpa"] / nominal}


def peterson_kt(p: dict) -> float:
    """U-groove, tension: Kt = C1 + C2 x + C3 x^2 + C4 x^3 with x = 2h / D."""
    h_r = 1 / p["r_over_h"]
    s = math.sqrt(h_r)
    if h_r <= 2.0:
        c = (0.89 + 2.208 * s - 0.094 * h_r, -0.923 - 6.678 * s + 1.638 * h_r,
             2.893 + 6.448 * s - 2.516 * h_r, -1.912 - 1.944 * s + 0.963 * h_r)
    else:
        c = (1.037 + 1.967 * s + 0.002 * h_r, -2.679 - 2.980 * s - 0.053 * h_r,
             3.090 + 2.124 * s + 0.165 * h_r, -0.424 - 1.153 * s - 0.106 * h_r)
    x = (p["D_over_d"] - 1) / p["D_over_d"]
    return c[0] + c[1] * x + c[2] * x ** 2 + c[3] * x ** 3


def references(p: dict, s: dict, nd: dict) -> dict:
    return {"kt_over_peterson": nd["kt"] / peterson_kt(p), "peak_angle_deg": s["groove_deg"]}


def mirror_err(s: dict) -> float:
    return abs(s["groove_s1_mpa"] - s["groove_s1_other_mpa"]) / max(abs(s["groove_s1_mpa"]), 1e-30)
