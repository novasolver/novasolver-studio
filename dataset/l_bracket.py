"""Family 1: shelf L-bracket. The back of the vertical flange is fixed to a wall (x = 0); a force pushes down on the
top of the horizontal flange; the inner corner has a fillet of radius R, where the stress concentrates.

Lengths are scaled by the flange length L (L = 80 mm in the solves). In linear elasticity with E, F and L scaled out
exactly (stress * L^2 / F and deflection * E * L / F depend only on the shape ratios and nu), each solve stands for
every size, material stiffness and load of the same shape: 5 dimensions instead of 9."""
from __future__ import annotations

from pathlib import Path

L = 80.0                      # mm, flange length used in every solve
F = 1000.0                    # N, total downward force on the top face of the horizontal flange
E = 200e9                     # Pa (scaled out; any value gives the same nondimensional result)

# nondimensional parameters and their ranges (the family)
PARAMS = {
    "h_over_L": (0.4, 1.0),       # height of the vertical flange / L
    "t_over_L": (0.04, 0.15),     # plate thickness / L
    "w_over_L": (0.25, 0.75),     # width (y) / L
    "r_over_t": (0.25, 1.5),      # inner fillet radius / thickness (0 would be a sharp corner: a singular stress)
    "nu": (0.25, 0.35),           # Poisson's ratio
}


# Which way each answer must move when a parameter grows (checked over the whole space by analyze.py):
# a thicker plate is stiffer and less stressed (strongly); a wider one spreads the same force (less stress, less
# deflection); a larger fillet lowers the concentration. 0 = should hardly matter.
EXPECTED_DIRECTIONS = {
    "sigma_star": {"t_over_L": -1, "w_over_L": -1, "r_over_t": -1},
    "delta_star": {"t_over_L": -1, "w_over_L": -1, "h_over_L": 0},
}


def dims(p: dict, scale: float = 1.0) -> dict:
    """Dimensions in mm for a parameter point (scale multiplies every length: used by the similarity check)."""
    s = L * scale
    t = p["t_over_L"] * s
    return {"L": s, "H": p["h_over_L"] * s, "t": t, "W": p["w_over_L"] * s, "R": p["r_over_t"] * t}


def write_step(p: dict, path: Path, scale: float = 1.0) -> None:
    import gmsh
    d = dims(p, scale)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("bracket")
        occ = gmsh.model.occ
        base = occ.addBox(0, 0, 0, d["L"], d["W"], d["t"])            # horizontal flange (loaded on top)
        wall = occ.addBox(0, 0, 0, d["t"], d["W"], d["H"])            # vertical flange (back face x = 0 on the wall)
        out, _ = occ.fuse([(3, base)], [(3, wall)])
        occ.synchronize()
        vol = out[0][1]
        # the inner corner edge: along y at x = t, z = t
        tol = 1e-4 * d["L"]
        inner = [e for _, e in gmsh.model.getEntitiesInBoundingBox(d["t"] - tol, -tol, d["t"] - tol,
                                                                     d["t"] + tol, d["W"] + tol, d["t"] + tol, 1)]
        assert len(inner) == 1, f"inner corner edge not found ({len(inner)})"
        occ.fillet([vol], inner, [d["R"]])
        occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()


def fillet_arc(p: dict, scale: float = 1.0, n: int = 61) -> list[list[float]]:
    """Points on the fillet surface along its arc at mid-width, from the horizontal flange (0 deg) to the vertical one
    (90 deg), 0.5 % of R inside the material. The peak of these is the fillet stress the dataset reports: a single
    curve sampled with the element's own interpolation, steadier than the largest nodal value over the whole face."""
    import math
    d = dims(p, scale)
    cx = cz = d["t"] + d["R"]                       # arc centre (in the empty corner); the material is beyond R
    r = d["R"] * 1.005
    out = []
    for i in range(n):
        a = math.radians(90 * i / (n - 1))
        # 0 deg: the point below the centre (on the horizontal flange's top); 90 deg: left of it (vertical flange)
        out.append([cx - r * math.sin(a), d["W"] / 2, cz - r * math.cos(a)])
    return out


QUANTITIES = ("sigma_star", "delta_star")
# the neighbour fit is made on what is left after the known theory is divided out (see analyze.py)
NORMALISED = {"sigma_star": "kt", "delta_star": "beam_ratio"}
CHECK_EQUILIBRIUM = True


def refine_face(faces: list[dict]) -> str:
    fillet = [f["key"] for f in faces if f.get("type") == "Cylinder"]
    assert len(fillet) == 1, fillet
    return fillet[0]


def refine_length(p: dict, scale: float = 1.0) -> float:
    return dims(p, scale)["R"]


def measure(C, cid: str, p: dict, scale: float, refine_key: str) -> dict:
    d = dims(p, scale)
    pts = [[d["L"], d["W"] / 2, d["t"]], [d["L"], 0.2 * d["W"], d["t"]], [d["L"], 0.8 * d["W"], d["t"]]]
    arc = fillet_arc(p, scale)
    pr = C.probe_results(cid, pts + arc, None, [refine_key], None, "en", 1, None)
    uz = [pt["values"]["uz"] for pt in pr["points"][:3]]
    arc_vm = [pt["values"]["vm"] for pt in pr["points"][3:]]
    k = max(range(len(arc_vm)), key=arc_vm.__getitem__)
    return {"fillet_arc_vm_mpa": arc_vm[k], "fillet_arc_deg": round(90 * k / (len(arc_vm) - 1), 1),
            "arc_inside": sum(pt["inside"] for pt in pr["points"][3:]) / len(arc),
            "fillet_face_max_vm_mpa": pr["faces"][0]["max"]["vm"], "tip_uz_mm": uz[0], "mirror_uz_mm": uz[1:]}


def nondim(s: dict, p: dict, scale: float = 1.0, force: float = F) -> dict:
    Lmm = L * scale
    return {"sigma_star": s["fillet_arc_vm_mpa"] * Lmm ** 2 / force,
            "delta_star": abs(s["tip_uz_mm"]) * (E / 1e6) * Lmm / force}


def beam_tip(p: dict) -> float:
    """Euler-Bernoulli cantilever (the horizontal flange, clamped at x = t) under the force spread evenly over the
    loaded face x in [t + R, L]: a reference for slender brackets, not for thick ones (shear, corner flexibility)."""
    d = dims(p)
    I = d["W"] * d["t"] ** 3 / 12
    a, b = d["R"], d["L"] - d["t"]                                 # load from a to b, measured from the clamp
    q = F / (b - a)
    # w(b) = int_a^b q x^2 (3b - x) / (6 E I) dx
    return q * (b * (b ** 3 - a ** 3) - (b ** 4 - a ** 4) / 4) / 6 / ((E / 1e6) * I)


def references(p: dict, s: dict, nd: dict) -> dict:
    d = dims(p)
    # nominal bending stress at the root of the horizontal flange (load centroid to x = t)
    nominal = 6 * F * ((d["t"] + d["R"] + d["L"]) / 2 - d["t"]) / (d["W"] * d["t"] ** 2)
    return {"kt": s["fillet_arc_vm_mpa"] / nominal, "beam_ratio": abs(s["tip_uz_mm"]) / beam_tip(p),
            "peak_angle_deg": s["fillet_arc_deg"]}


def mirror_err(s: dict) -> float:
    m = s["mirror_uz_mm"]
    return abs(m[0] - m[1]) / max(abs(m[0]), 1e-30)


def boundary_changes(faces: list[dict], p: dict, scale: float = 1.0, force: float = F) -> dict:
    """update_case changes: fixed = the plane at x = 0; load = the plane at z = t with x beyond the fillet."""
    d = dims(p, scale)
    fixed = [f["key"] for f in faces if f.get("normal") and f["normal"][0] < -0.99 and abs(f["centroid_mm"][0]) < 1e-3 * d["L"]]
    top = [f["key"] for f in faces if f.get("normal") and f["normal"][2] > 0.99
           and abs(f["centroid_mm"][2] - d["t"]) < 1e-3 * d["L"] and f["centroid_mm"][0] > d["t"] + d["R"]]
    assert len(fixed) == 1 and len(top) == 1, (fixed, top)
    return {f"boundaries.{fixed[0]}.role": "fixed",
            f"boundaries.{top[0]}.role": "load", f"boundaries.{top[0]}.force": f"{force} N",
            f"boundaries.{top[0]}.direction": "-z"}
