"""Family 13: direct current in a flat busbar with a round hole (a bolt hole), possibly off the centre line.

How much the hole adds to the resistance and how much it crowds the current, the two numbers a busbar designer needs.
Hand anchor for a small hole in a wide strip: the extra resistance equals extra strip length pi d^2 / (2 W) (Maxwell's
dilute limit), and the current density at the hole's side reaches twice the local value. Half the strip is solved along
the length (the mid plane is at half voltage); the far end is long enough for the current to be uniform again."""
from __future__ import annotations

import math
from pathlib import Path

PHYSICS = "current"
W0 = 40.0                     # mm, strip width
T0 = 4.0                      # mm
LH_OVER_W = 2.0               # half length / W
VOLT_MV = 10.0                # mV across the half length
SIGMA = 5.8e7                 # S/m
F = 1.0
E = 1.0
LEVELS = {"coarser": 1 / 8, "standard": 1 / 16, "finer": 1 / 32}   # element size on the hole / its diameter
MESH_SIZE = "normal"
GCI_EVERY = 5
CALCULIX = False
PARAMS = {"d_over_W": (0.05, 0.6), "e_over_W": (0.0, 0.15)}        # hole offset from the centre line / W
QUANTITIES = ("dl_over_W", "kj")
NORMALISED = {"dl_over_W": "dl_over_maxwell", "kj": "kj"}
EXPECTED_DIRECTIONS = {"dl_over_W": {"d_over_W": 1}}
CHECK_EQUILIBRIUM = False
PICTURE_QUANTITY = "jmag"     # the crowding at the hole, not the voltage falling along the strip


def dims(p, scale=1.0):
    W = W0 * scale
    return {"W": W, "t": T0 * scale, "d": p["d_over_W"] * W, "e": p["e_over_W"] * W, "Lh": LH_OVER_W * W}


def write_step(p, path: Path, scale=1.0):
    import gmsh
    d = dims(p, scale)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("strip")
        occ = gmsh.model.occ
        box = occ.addBox(0, -d["W"] / 2, 0, d["Lh"], d["W"], d["t"])
        hole = occ.addCylinder(0, d["e"], -d["t"], 0, 0, 3 * d["t"], d["d"] / 2)
        occ.rotate([(3, hole)], 0, d["e"], 0, 0, 0, 1, 3.141592653589793)   # its seam goes outside the half that stays
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
    mid = [f["key"] for f in faces if f.get("normal") and f["normal"][0] < -0.99 and abs(f["centroid_mm"][0]) < tol]
    end = [f["key"] for f in faces if f.get("normal") and f["normal"][0] > 0.99 and abs(f["centroid_mm"][0] - d["Lh"]) < tol]
    assert len(mid) == 2 and len(end) == 1, (mid, end)                   # the hole splits the mid plane in two
    ch = {f"boundaries.{end[0]}.role": "voltage", f"boundaries.{end[0]}.voltage": f"{VOLT_MV * 1e-3} V"}
    for k in mid:
        ch.update({f"boundaries.{k}.role": "voltage", f"boundaries.{k}.voltage": "0 V"})
    for f in faces:
        if f["key"] not in mid and f["key"] != end[0]:
            ch[f"boundaries.{f['key']}.role"] = "insulated"
    return ch


def extra_changes(p, scale, force):
    return {"physics.joule_heating": False, "materials.solid.preset": "custom", "materials.solid.sigma": f"{SIGMA} S/m"}


def measure(C, cid, p, scale, refine_key):
    import core
    m = core.metrics(cid)
    return {"current_a": m["current_a"], "j_max_a_mm2": m["j_max_a_m2"] / 1e6}


def nondim(s, p, scale=1.0, force=F):
    """Extra length of plain strip the hole is worth, over W, and the peak current density over the mean in the far strip.
    The mid plane cuts the hole in half, so the half model carries half the hole's extra length: doubled."""
    d = dims(p, scale)
    area = d["W"] * d["t"] * 1e-6
    r_half = VOLT_MV * 1e-3 / abs(s["current_a"])
    plain = (d["Lh"] * 1e-3) / (SIGMA * area)
    extra_len = 2 * (r_half - plain) * SIGMA * area / (d["W"] * 1e-3)
    jmean = abs(s["current_a"]) / (area * 1e6)
    return {"dl_over_W": extra_len, "kj": s["j_max_a_mm2"] / jmean}


def maxwell(p):
    return math.pi * p["d_over_W"] ** 2 / 2


def references(p, s, nd):
    return {"dl_over_maxwell": nd["dl_over_W"] / maxwell(p)}


def mirror_err(s):
    return 0.0
