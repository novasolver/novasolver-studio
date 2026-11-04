"""Family 11: heat flowing from a round hole to the outside of a rectangular block (a pipe in a square of insulation).

The conduction shape factor S* = q / (k D_len theta) of a long block. Hand anchor for a square section (H/W = 1): the
textbook fit S* = 2 pi / ln(1.08 W / d), good by about 1 % for a small hole. A tall block with a small hole approaches
the strip between two walls, S* = 2 pi / ln(4 W / (pi d)). Between them no simple formula holds, which is why the rest of
the space is worth having. A quarter of the section is solved, as a thin slice: the end faces and the two symmetry planes
carry no heat."""
from __future__ import annotations

import math
from pathlib import Path

PHYSICS = "thermal"
W0 = 100.0                    # mm, block width
SLICE = 10.0                  # mm of length
K = 1.0                       # W/mK
THETA = 100.0                 # K, hole above the outside
F = 1.0
E = 1.0
LEVELS = {"coarser": 1 / 8, "standard": 1 / 16, "finer": 1 / 32}   # element size on the hole / its diameter
MESH_SIZE = "normal"
GCI_EVERY = 5
CALCULIX = False
PARAMS = {"d_over_W": (0.1, 0.8), "H_over_W": (1.0, 3.0)}
QUANTITIES = ("s_star",)
NORMALISED = {"s_star": "s_over_fit"}
# a taller block moves the top and bottom walls away and the side walls stay: less heat, down to the strip's value
EXPECTED_DIRECTIONS = {"s_star": {"d_over_W": 1, "H_over_W": -1}}
CHECK_EQUILIBRIUM = False


def dims(p, scale=1.0):
    W = W0 * scale
    return {"W": W, "H": p["H_over_W"] * W, "d": p["d_over_W"] * W, "len": SLICE * scale}


def write_step(p, path: Path, scale=1.0):
    import gmsh
    d = dims(p, scale)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("block")
        occ = gmsh.model.occ
        box = occ.addBox(0, 0, 0, d["W"] / 2, d["H"] / 2, d["len"])
        hole = occ.addCylinder(0, 0, -d["len"], 0, 0, 3 * d["len"], d["d"] / 2)
        occ.cut([(3, box)], [(3, hole)])
        occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()


def refine_face(faces):
    hit = [f["key"] for f in faces if f.get("type") == "Cylinder"]
    assert len(hit) == 1, hit
    return hit[0]


def refine_length(p, scale=1.0):
    return dims(p, scale)["d"]


def boundary_changes(faces, p, scale=1.0, force=F):
    d = dims(p, scale)
    tol = 1e-3 * d["W"]
    outer = [f["key"] for f in faces if f.get("normal") and (
        (f["normal"][0] > 0.99 and abs(f["centroid_mm"][0] - d["W"] / 2) < tol) or
        (f["normal"][1] > 0.99 and abs(f["centroid_mm"][1] - d["H"] / 2) < tol))]
    hole = refine_face(faces)
    assert len(outer) == 2, outer
    ch = {f"boundaries.{hole}.role": "temperature", f"boundaries.{hole}.temperature": f"{THETA} degC"}
    for k in outer:
        ch.update({f"boundaries.{k}.role": "temperature", f"boundaries.{k}.temperature": "0 degC"})
    for f in faces:
        if f["key"] != hole and f["key"] not in outer:
            ch[f"boundaries.{f['key']}.role"] = "insulated"
    return ch


def extra_changes(p, scale, force):
    return {"materials.solid.preset": "custom", "materials.solid.k": f"{K} W/mK"}


def measure(C, cid, p, scale, refine_key):
    import core
    return {"q_w": core.metrics(cid)["q_in_w"]}


def nondim(s, p, scale=1.0, force=F):
    """Whole section (4 quarters), per unit length."""
    return {"s_star": 4 * abs(s["q_w"]) / (K * dims(p, scale)["len"] * 1e-3 * THETA)}


def fit(p):
    return 2 * math.pi / math.log(1.08 / p["d_over_W"])


def references(p, s, nd):
    return {"s_over_fit": nd["s_star"] / fit(p), "s_over_strip": nd["s_star"] / (2 * math.pi / math.log(4 / (math.pi * p["d_over_W"])))}


def mirror_err(s):
    return 0.0
