"""Family 2: a plate of width W and thickness t with a central through hole of diameter d, pulled along x.

The classic stress concentration: at the hole edge on the x = 0 section the axial stress peaks. Hand-checkable anchors:
Kirsch (infinite thin plate: Kt = 3 on the gross stress), Howland's finite-width values in Pilkey's fit for thin plates,
and the 3D thickness effect (the mid-plane value rises a few % above the plane-stress one as t/d and nu grow).

Only one eighth is solved: symmetry on x = 0, y = 0 and the mid-plane z = 0; the end face x = Lh is pulled with a
uniform traction. Lengths are scaled by W (W = 40 mm in the solves); in linear elasticity
Kt and the compliance E * t * u_end / (F * (Lh / W)) depend only on d/W, t/W and nu."""
from __future__ import annotations

import math
from pathlib import Path

W = 40.0                      # mm, plate width used in every solve
LH_OVER_W = 1.5               # half length / W: the end is 1.5 W from the hole, well past its influence
F = 1000.0                    # N on the solved eighth (quarter of the cross-section): nominal gross stress F / (W t / 4)
E = 200e9                     # Pa

PARAMS = {
    "d_over_W": (0.1, 0.6),       # hole diameter / width
    "t_over_W": (0.05, 0.5),      # thickness / width (thin: plane stress; thick: the 3D effect shows)
    "nu": (0.25, 0.35),
}

# a bigger hole concentrates less on the net section; thickness and nu only shift the mid-plane value slightly up
EXPECTED_DIRECTIONS = {
    "kt_net": {"d_over_W": -1},
    "compliance_star": {"d_over_W": 1, "t_over_W": 0},
}
QUANTITIES = ("kt_net", "compliance_star")


def dims(p: dict, scale: float = 1.0) -> dict:
    s = W * scale
    return {"W": s, "t": p["t_over_W"] * s, "d": p["d_over_W"] * s, "r": p["d_over_W"] * s / 2, "Lh": LH_OVER_W * s}


def write_step(p: dict, path: Path, scale: float = 1.0) -> None:
    import gmsh
    d = dims(p, scale)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("plate")
        occ = gmsh.model.occ
        box = occ.addBox(0, 0, 0, d["Lh"], d["W"] / 2, d["t"] / 2)
        hole = occ.addCylinder(0, 0, -d["t"], 0, 0, 2 * d["t"], d["r"])
        occ.cut([(3, box)], [(3, hole)])
        occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()


def refine_face(faces: list[dict]) -> str:
    hole = [f["key"] for f in faces if f.get("type") == "Cylinder"]
    assert len(hole) == 1, hole
    return hole[0]


def refine_length(p: dict, scale: float = 1.0) -> float:
    """The length the refinement levels are measured against (element size = level * this): the hole radius."""
    return dims(p, scale)["r"]


def boundary_changes(faces: list[dict], p: dict, scale: float = 1.0, force: float = F) -> dict:
    d = dims(p, scale)
    tol = 1e-3 * d["W"]
    def plane(axis, value, sign):
        return [f["key"] for f in faces if f.get("normal") and sign * f["normal"][axis] > 0.99
                and abs(f["centroid_mm"][axis] - value) < tol]
    sx, sy, sz, end = plane(0, 0, -1), plane(1, 0, -1), plane(2, 0, -1), plane(0, d["Lh"], 1)
    assert len(sx) == len(sy) == len(sz) == len(end) == 1, (sx, sy, sz, end)
    return {f"boundaries.{sx[0]}.role": "symmetry", f"boundaries.{sy[0]}.role": "symmetry",
            f"boundaries.{sz[0]}.role": "symmetry",
            f"boundaries.{end[0]}.role": "load", f"boundaries.{end[0]}.force": f"{force} N",
            f"boundaries.{end[0]}.direction": "+x"}


DEPTHS = (0.005, 0.01)        # probe depths / r; the surface value is extrapolated linearly from the two


def probe_points(p: dict, scale: float = 1.0, n: int = 21) -> dict:
    """Where the dataset reads the answers: the hole edge on the x = 0 section through the half thickness at two depths
    (0.5 and 1 % of r inside the material), the end face (mean axial displacement) and mirror points on the end face."""
    d = dims(p, scale)
    edges = [[[0.0, d["r"] * (1 + dp), d["t"] / 2 * i / (n - 1) * 0.999] for i in range(n)] for dp in DEPTHS]
    end = [[d["Lh"], d["W"] / 2 * f, d["t"] / 2 * g] for f in (0.1, 0.5, 0.9) for g in (0.0, 0.5, 1.0)]
    return {"edge": edges[0], "edge2": edges[1], "end": end}


def measure(C, cid: str, p: dict, scale: float, refine_key: str) -> dict:
    """The hole-edge stress is extrapolated to the surface from the two depths: 0.5 % of r inside, Kirsch's field
    has already fallen by about 1 %."""
    pts = probe_points(p, scale)
    n = len(pts["edge"])
    pr = C.probe_results(cid, pts["edge"] + pts["edge2"] + pts["end"], None, [refine_key], None, "en", 1, None)
    vals = [pt["values"] for pt in pr["points"]]
    e1, e2, end = vals[:n], vals[n:2 * n], vals[2 * n:]
    w = DEPTHS[0] / (DEPTHS[1] - DEPTHS[0])
    sxx = [a["sxx"] + w * (a["sxx"] - b["sxx"]) for a, b in zip(e1, e2)]
    edge = e1
    return {"edge_sxx_mid_mpa": sxx[0], "edge_sxx_max_mpa": max(sxx),
            "edge_sxx_max_z_frac": round(sxx.index(max(sxx)) / (len(sxx) - 1), 3),
            "edge_sxx_mid_probe_mpa": e1[0]["sxx"],
            "edge_inside": sum(pt["inside"] for pt in pr["points"][:2 * n]) / (2 * n),
            "end_ux_mm": sum(v["ux"] for v in end) / len(end),
            "end_ux_spread": (max(v["ux"] for v in end) - min(v["ux"] for v in end)),
            "hole_face_max_vm_mpa": pr["faces"][0]["max"]["vm"]}


def nondim(s: dict, p: dict, scale: float = 1.0, force: float = F) -> dict:
    """Kt on the net section at the mid-plane, and the end compliance per unit length (1 for a plate without a hole)."""
    d = dims(p, scale)
    gross = force / (d["W"] / 2 * d["t"] / 2)                     # MPa (N / mm2)
    net = gross * d["W"] / (d["W"] - d["d"])
    strain = s["end_ux_mm"] / d["Lh"]
    return {"kt_net": s["edge_sxx_mid_mpa"] / net,
            "compliance_star": strain * (E / 1e6) / gross}


def pilkey_kt_net(dw: float) -> float:
    """Howland's thin-plate values as fitted in Peterson's Stress Concentration Factors (Pilkey), net section."""
    return 3.000 - 3.140 * dw + 3.667 * dw ** 2 - 1.527 * dw ** 3


def references(p: dict, s: dict, nd: dict) -> dict:
    """Ratios to hand theory; used both as checks and to take the known trend out before the neighbour fit."""
    return {"kt_over_pilkey": nd["kt_net"] / pilkey_kt_net(p["d_over_W"]),
            # mid-plane vs through-thickness peak: 1 for a thin plate
            "kt_peak_over_mid": s["edge_sxx_max_mpa"] / s["edge_sxx_mid_mpa"]}


NORMALISED = {"kt_net": "kt_over_pilkey", "compliance_star": "compliance_star"}


def mirror_err(s: dict) -> float:
    """No mirror pair here (the symmetry is imposed); the spread of the end displacement over the face instead."""
    return abs(s["end_ux_spread"]) / max(abs(s["end_ux_mm"]), 1e-30)
