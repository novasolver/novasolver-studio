"""Family 5: a round bar with a spherical cavity at its centre, in tension.

Exact anchor: Goodier's solution for a spherical cavity in an infinite body under uniaxial tension, peak stress at the
equator Kt = 3 (9 - 5 nu) / (2 (7 - 5 nu)) (2.045 at nu = 0.3), the one textbook concentration that depends on Poisson's
ratio. A small cavity in the bar must approach it; a large one rises above it (the bar's own section is used up).
An eighth is solved (symmetry on x = 0, y = 0 and on the cavity's equatorial plane z = 0); the far end is pulled.
Lengths are scaled by the bar radius (20 mm in the solves)."""
from __future__ import annotations

import math
from pathlib import Path

R_BAR = 20.0                  # mm
LH_OVER_R = 2.5               # half length / bar radius (the end is far from the cavity)
F = 1000.0                    # N on the quarter section
E = 200e9

PARAMS = {
    "a_over_R": (0.1, 0.6),   # cavity radius / bar radius
    "nu": (0.0, 0.45),
}
EXPECTED_DIRECTIONS = {"kt": {"a_over_R": 1, "nu": 1}}
QUANTITIES = ("kt",)
NORMALISED = {"kt": "kt_over_goodier"}
MIRROR_BOUNDS = ("kt",)       # two azimuths measure the same axisymmetric peak
CHECK_EQUILIBRIUM = False     # the load is carried by symmetry planes
MESH_SIZE = "normal"          # a coarse body with a refined cavity made mesh studies non-monotone (stepped shaft)
# a/16 on the cavity was 0.4-0.9 % below Goodier at a/R = 0.1, a/32 within 0.25 % for nu = 0, 0.3, 0.45 (75k nodes)
LEVELS = {"coarser": 1 / 16, "standard": 1 / 32, "finer": 1 / 64}


def dims(p: dict, scale: float = 1.0) -> dict:
    R = R_BAR * scale
    return {"R": R, "a": p["a_over_R"] * R, "Lh": LH_OVER_R * R}


def write_step(p: dict, path: Path, scale: float = 1.0) -> None:
    import gmsh
    g = dims(p, scale)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("cavity")
        occ = gmsh.model.occ
        bar = occ.addCylinder(0, 0, 0, 0, 0, g["Lh"], g["R"])
        ball = occ.addSphere(0, 0, 0, g["a"])
        out, _ = occ.cut([(3, bar)], [(3, ball)])
        box = occ.addBox(0, 0, 0, 2 * g["R"], 2 * g["R"], 2 * g["Lh"])
        occ.intersect(out, [(3, box)])
        occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()


def refine_face(faces: list[dict]) -> str:
    sph = [f["key"] for f in faces if f.get("type") == "Sphere"]
    assert len(sph) == 1, [(f["key"], f.get("type")) for f in faces]
    return sph[0]


def refine_length(p: dict, scale: float = 1.0) -> float:
    return dims(p, scale)["a"]


def boundary_changes(faces: list[dict], p: dict, scale: float = 1.0, force: float = F) -> dict:
    g = dims(p, scale)
    tol = 1e-3 * g["R"]
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


def meridian(p: dict, scale: float, phi_deg: float, depth: float, n: int = 31) -> list[list[float]]:
    """From the equator (0 deg) 30 deg up the cavity wall at azimuth phi, depth x a inside the material."""
    a = dims(p, scale)["a"] * (1 + depth)
    ph = math.radians(phi_deg)
    out = []
    for i in range(n):
        th = math.radians(30 * i / (n - 1))
        rho, z = a * math.cos(th), a * math.sin(th)
        out.append([rho * math.cos(ph), rho * math.sin(ph), z])
    return out


DEPTHS = (0.005, 0.01)        # probe depths / a; the surface value is extrapolated linearly from the two
VIEW = (24, -148)                    # picture.py: the cavity faces the camera


def measure(C, cid: str, p: dict, scale: float, refine_key: str) -> dict:
    """Surface peak of s1 on two azimuths. A probe must sit inside the material, where the stress has already fallen
    (by ~1.2 % at 0.5 % of a for Goodier's field), so two depths are probed and extrapolated to the wall."""
    arcs = [meridian(p, scale, phi, dp) for phi in (20.0, 70.0) for dp in DEPTHS]
    pr = C.probe_results(cid, [q for arc in arcs for q in arc], None, [refine_key], None, "en", 1, None)
    s1 = [pt["values"]["s1"] for pt in pr["points"]]
    n = len(arcs[0])
    a1, a2, b1, b2 = (s1[i * n:(i + 1) * n] for i in range(4))
    w = DEPTHS[0] / (DEPTHS[1] - DEPTHS[0])
    a = [x + w * (x - y) for x, y in zip(a1, a2)]
    b = [x + w * (x - y) for x, y in zip(b1, b2)]
    k = max(range(n), key=a.__getitem__)
    return {"cavity_s1_mpa": a[k], "cavity_s1_other_mpa": max(b), "cavity_s1_probe_mpa": a1[k],
            "peak_deg": round(30 * k / (n - 1), 1),
            "arc_inside": sum(pt["inside"] for pt in pr["points"]) / len(pr["points"])}


def nondim(s: dict, p: dict, scale: float = 1.0, force: float = F) -> dict:
    """kt on the gross section (Goodier's definition: the stress far from the cavity)."""
    R = dims(p, scale)["R"]
    return {"kt": s["cavity_s1_mpa"] / (force / (math.pi * R ** 2 / 4))}


def goodier_kt(nu: float) -> float:
    return 3 * (9 - 5 * nu) / (2 * (7 - 5 * nu))


def references(p: dict, s: dict, nd: dict) -> dict:
    return {"kt_over_goodier": nd["kt"] / goodier_kt(p["nu"]), "peak_deg": s["peak_deg"]}


def mirror_err(s: dict) -> float:
    return abs(s["cavity_s1_mpa"] - s["cavity_s1_other_mpa"]) / max(abs(s["cavity_s1_mpa"]), 1e-30)
