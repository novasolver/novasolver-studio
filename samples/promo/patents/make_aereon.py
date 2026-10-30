"""US 43,449 (1864) Solomon Andrews' 'Aereon', from the dimensions in its specification:
three cylindroids of varnished linen, each 80 ft (24.38 m) long and 13 ft (3.96 m) in diameter, 48 ft cylindrical in
the middle and tapering to a point over 16 ft at each end, joined side by side at their equators; flat cambric
diaphragms fill the gaps between the pointed ends. The car (16 ft below), net and rudder are left out: the
aerodynamic forces come from the gas bags.

Modelled with the bags overlapping by 4 % of the diameter (exactly tangent cylinders cannot be fused into one
solid) and the diaphragms as 5 cm plates. Units mm.  python make_aereon.py
"""
from pathlib import Path

import gmsh

OUT = Path(__file__).parent
FT = 304.8
L, D, CONE = 80 * FT, 13 * FT, 16 * FT
R = D / 2
PITCH = 0.96 * D


def bag(y):
    occ = gmsh.model.occ
    mid = occ.addCylinder(CONE, y, 0, L - 2 * CONE, 0, 0, R)
    nose = occ.addCone(CONE, y, 0, -CONE, 0, 0, R, 0)
    tail = occ.addCone(L - CONE, y, 0, CONE, 0, 0, R, 0)
    return [(3, mid), (3, nose), (3, tail)]


def build(pitch=0.0):
    gmsh.model.add("aereon")
    occ = gmsh.model.occ
    parts = bag(-PITCH) + bag(0) + bag(PITCH)
    # diaphragms: triangular sheets at the equator filling the gap between the points of two neighbouring bags;
    # the gap closes where the cones touch, x = CONE * PITCH / D from each end
    xc = CONE * PITCH / D
    for yl in (-PITCH, 0):
        for nose in (True, False):
            xs = (0, 0, xc) if nose else (L, L, L - xc)
            pts = [occ.addPoint(xs[0], yl, -25), occ.addPoint(xs[1], yl + PITCH, -25), occ.addPoint(xs[2], yl + PITCH / 2, -25)]
            loop = occ.addCurveLoop([occ.addLine(pts[0], pts[1]), occ.addLine(pts[1], pts[2]), occ.addLine(pts[2], pts[0])])
            sheet = occ.addPlaneSurface([loop])
            parts += [e for e in occ.extrude([(2, sheet)], 0, 0, 50) if e[0] == 3]
    body, _ = occ.fuse(parts[:1], parts[1:])
    if pitch:                                            # nose (x = 0) up by `pitch` degrees, about the middle
        import math
        occ.rotate(body, L / 2, 0, 0, 0, 1, 0, math.radians(pitch))
    occ.synchronize()
    gmsh.write(str(OUT / (f"aereon_a{pitch:g}.step" if pitch else "aereon.step")))


if __name__ == "__main__":
    gmsh.initialize(["", "-nopopup"])
    gmsh.option.setNumber("General.Terminal", 0)
    try:
        build()
        build(10)
    finally:
        gmsh.finalize()
    print("ok", OUT / "aereon.step")

