"""Family 4: a round shaft stepping from diameter D down to d with a shoulder fillet of radius r, in tension.

The textbook case of machine design. Reference: Peterson's charts as fitted in Pilkey (stepped bar of circular
cross section, tension), a trend check only, not a certificate: Peterson's shoulder-fillet curves were estimated from
related geometries and are known to run low, by up to 24 % (Tipton, Sorem and Schmidt, Univ. of Tulsa, FEA) and up to
25 % in tension at small radii (Oda, Takahata, Yamashita, Noda, J. Japan Soc. Design Eng. 61(3), 2025, body force
method). The certificate here is the mesh study, CalculiX and the axisymmetry check.
A quarter is solved (symmetry on x = 0 and y = 0); the end of the small shaft is a symmetry plane (z = 0, as if the
bar continued mirror-wise), the end of the large one is pulled. Lengths are scaled by d (d = 20 mm in the solves)."""
from __future__ import annotations

import math
from pathlib import Path

D_SMALL = 20.0                # mm
LS_OVER_d = 1.5               # small shaft length / d (fillet end to the symmetry plane)
LL_OVER_D = 1.5               # large shaft length / D
F = 1000.0                    # N on the quarter
E = 200e9

# The fillet must fit inside the step (r < h = (D - d) / 2, or it would run past the large diameter), so it is
# sampled as a fraction of the step: a rectangular parameter box with every point buildable. v1 sampled r/d and D/d
# independently and a quarter of its points could not be built.
PARAMS = {
    "D_over_d": (1.2, 2.0),
    "r_over_h": (0.2, 0.9),        # fillet radius / step height (r/d >= 0.02); Peterson's h/r from 1.1 to 5
    "nu": (0.25, 0.35),
}
# a bigger fillet relative to its step concentrates less; at a fixed r/h a bigger step also has a bigger fillet,
# so D/d has no single expected direction
EXPECTED_DIRECTIONS = {"kt": {"r_over_h": -1, "nu": 0}}
QUANTITIES = ("kt",)
NORMALISED = {"kt": "kt_over_peterson"}
MIRROR_BOUNDS = ("kt",)        # the two meridian planes measure kt twice: their gap bounds its error
CHECK_EQUILIBRIUM = False      # the load is carried by a symmetry plane, not a fixed face
# With Studio's coarse global mesh the size fell from the fillet to the body within a few elements and the mesh study
# did not converge (id 10: 2.309 / 2.354 / 2.273, half the studies non-monotone); a normal global mesh gives
# 2.344 / 2.342 / 2.342 for 1.5x the time.
MESH_SIZE = "normal"


def dims(p: dict, scale: float = 1.0) -> dict:
    d = D_SMALL * scale
    D = p["D_over_d"] * d
    r = p["r_over_h"] * (D - d) / 2
    return {"d": d, "D": D, "r": r, "Ls": LS_OVER_d * d, "Ll": LL_OVER_D * D}


def write_step(p: dict, path: Path, scale: float = 1.0) -> None:
    import gmsh
    g = dims(p, scale)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("shaft")
        occ = gmsh.model.occ
        small = occ.addCylinder(0, 0, 0, 0, 0, g["Ls"] + 0.5 * g["Ll"], g["d"] / 2)
        large = occ.addCylinder(0, 0, g["Ls"], 0, 0, g["Ll"], g["D"] / 2)
        out, _ = occ.fuse([(3, small)], [(3, large)])
        occ.synchronize()
        vol = out[0][1]
        tol = 1e-4 * g["d"]
        rr = g["d"] / 2
        edges = [e for _, e in gmsh.model.getEntitiesInBoundingBox(-rr - tol, -rr - tol, g["Ls"] - tol,
                                                                     rr + tol, rr + tol, g["Ls"] + tol, 1)]
        assert len(edges) >= 1, "shoulder edge not found"
        occ.fillet([vol], edges, [g["r"]])
        occ.synchronize()
        vols = gmsh.model.getEntities(3)
        box = occ.addBox(0, 0, -g["Ls"], g["D"], g["D"], 3 * (g["Ls"] + g["Ll"]))
        occ.intersect(vols, [(3, box)])
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
    end = plane(2, g["Ls"] + g["Ll"], 1)
    assert len(sym) == 3 and len(end) == 1, (sym, end)
    ch = {f"boundaries.{k}.role": "symmetry" for k in sym}
    ch.update({f"boundaries.{end[0]}.role": "load", f"boundaries.{end[0]}.force": f"{force} N",
               f"boundaries.{end[0]}.direction": "+z"})
    return ch


DEPTHS = (0.005, 0.01)        # probe depths / r; the surface value is extrapolated linearly from the two


def fillet_arc(p: dict, scale: float = 1.0, phi_deg: float = 45.0, depth: float = 0.005,
               n: int = 61) -> list[list[float]]:
    """Points on the fillet in the meridian plane at phi, from where it meets the small shaft (0 deg) to the shoulder
    (90 deg), depth x r inside the material."""
    g = dims(p, scale)
    c_rho, c_z, R = g["d"] / 2 + g["r"], g["Ls"] - g["r"], g["r"] * (1 + depth)
    ph = math.radians(phi_deg)
    out = []
    for i in range(n):
        a = math.radians(90 * i / (n - 1))
        rho, z = c_rho - R * math.cos(a), c_z + R * math.sin(a)
        out.append([rho * math.cos(ph), rho * math.sin(ph), z])
    return out


def measure(C, cid: str, p: dict, scale: float, refine_key: str) -> dict:
    """Peak first principal stress along the fillet in two meridian planes (20 and 70 deg: equal in an axisymmetric
    answer, the family's 'mirror' check), extrapolated to the surface from two probe depths (a probe 0.5 % of r inside
    reads about 1 % low: the stress falls steeply away from the fillet; checked on Goodier's cavity, family 5)."""
    arcs = [fillet_arc(p, scale, phi, dp) for phi in (20.0, 70.0) for dp in DEPTHS]
    pr = C.probe_results(cid, [q for arc in arcs for q in arc], None, [refine_key], None, "en", 1, None)
    s1 = [pt["values"]["s1"] for pt in pr["points"]]
    n = len(arcs[0])
    a1, a2, b1, b2 = (s1[i * n:(i + 1) * n] for i in range(4))
    w = DEPTHS[0] / (DEPTHS[1] - DEPTHS[0])
    a = [x + w * (x - y) for x, y in zip(a1, a2)]
    b = [x + w * (x - y) for x, y in zip(b1, b2)]
    k = max(range(n), key=a.__getitem__)
    return {"fillet_s1_mpa": a[k], "fillet_s1_other_mpa": max(b), "fillet_s1_probe_mpa": a1[k],
            "fillet_deg": round(90 * k / (n - 1), 1),
            "arc_inside": sum(pt["inside"] for pt in pr["points"]) / len(pr["points"]),
            "fillet_face_max_vm_mpa": pr["faces"][0]["max"]["vm"]}


def nondim(s: dict, p: dict, scale: float = 1.0, force: float = F) -> dict:
    g = dims(p, scale)
    nominal = force / (math.pi * g["d"] ** 2 / 16)                 # quarter force over a quarter of the small section
    return {"kt": s["fillet_s1_mpa"] / nominal}


def peterson_kt(p: dict) -> float:
    """Pilkey's fit of Peterson's chart (stepped round bar, shoulder fillet, tension), 0.1 <= h/r <= 20."""
    h_r = 1 / p["r_over_h"]
    s = math.sqrt(h_r)
    if h_r <= 2.0:
        c = (0.926 + 1.157 * s - 0.099 * h_r, 0.012 - 3.036 * s + 0.961 * h_r,
             -0.302 + 3.977 * s - 1.744 * h_r, 0.365 - 2.098 * s + 0.878 * h_r)
    else:
        c = (1.200 + 0.860 * s - 0.022 * h_r, -1.805 - 0.346 * s - 0.038 * h_r,
             2.198 - 0.486 * s + 0.165 * h_r, -0.593 - 0.028 * s - 0.106 * h_r)
    x = (p["D_over_d"] - 1) / p["D_over_d"]                          # 2h / D
    return c[0] + c[1] * x + c[2] * x ** 2 + c[3] * x ** 3


def references(p: dict, s: dict, nd: dict) -> dict:
    return {"kt_over_peterson": nd["kt"] / peterson_kt(p), "peak_angle_deg": s["fillet_deg"]}


def mirror_err(s: dict) -> float:
    return abs(s["fillet_s1_mpa"] - s["fillet_s1_other_mpa"]) / max(abs(s["fillet_s1_mpa"]), 1e-30)
