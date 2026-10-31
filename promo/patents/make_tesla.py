"""US 1,119,732 (1914) N. Tesla, 'Apparatus for transmitting electrical energy': the air around the elevated terminal.

Dimensions scaled from the drawing to the 57 m Wardenclyffe tower: the terminal D is a torus, 30 m across, with a
7.4 m tube (major radius 11.3 m), its centre 57 m above the ground. Three terminals, each in the same air domain:
  smooth  - the torus alone (the large radius of curvature the patent asks for)
  bumps   - the torus covered with the half-spherical elements P (radius 0.6 m) of the drawing: 16 around the tube,
            96 around the axis ("separate elements ... arranged in close proximity ... the outside ideal surface
            enveloping them is of a large radius")
  disk    - a flat disk of the same 30 m diameter, 0.4 m thick with square edges, for contrast
The terminal is symmetric about the axis, so only a thin wedge of the air is modelled (1/192 of the turn, between
two planes through the axis); the wedge faces carry no field across them (the natural condition). The air reaches
250 m out and up; the ground (z = 0) and the far boundary are at 0 V. Written in mm (STEP files are read as mm).
python make_tesla.py
"""
import math
from pathlib import Path

import gmsh

OUT = Path(__file__).parent
MM = 1000.0
H, RD = 57.0 * MM, 250.0 * MM          # terminal centre height; air radius and height
R, r = 11.3 * MM, 3.7 * MM             # torus major and tube radius
NB_AROUND, NB_TUBE, RB = 96, 16, 0.6 * MM   # elements P: per turn about the axis, around the tube, their radius
WEDGE = 2 * math.pi / NB_AROUND / 2    # half a bump pitch: mirror planes through a bump and between two bumps


def air(occ):
    """Thin wedge of air between the planes at angle 0 and WEDGE about the z axis."""
    return occ.addCylinder(0, 0, 0, 0, 0, RD, RD, angle=WEDGE)


def build(kind):
    gmsh.model.add(kind)
    occ = gmsh.model.occ
    a = air(occ)
    if kind == "disk":
        tool = [(3, occ.addCylinder(0, 0, H - 0.2 * MM, 0, 0, 0.4 * MM, R + r))]
    else:
        tool = [(3, occ.addTorus(0, 0, H, R, r))]
        if kind == "bumps":
            # bumps at angle 0 (on the wedge plane, half inside) around the tube cross-section
            for k in range(NB_TUBE):
                t = 2 * math.pi * k / NB_TUBE
                rho, z = R + r * math.cos(t), H + r * math.sin(t)
                tool.append((3, occ.addSphere(rho, 0, z, RB)))
    occ.cut([(3, a)], tool)
    occ.synchronize()
    gmsh.write(str(OUT / f"tesla_{kind}.step"))


if __name__ == "__main__":
    gmsh.initialize(["", "-nopopup"])
    gmsh.option.setNumber("General.Terminal", 0)
    try:
        for kind in ("smooth", "bumps", "disk"):
            build(kind)
    finally:
        gmsh.finalize()
    print("ok")
