"""US 35,600 (1862) 'Combined plow and gun' by C. M. French and W. H. Fancher, rebuilt from the proportions of
its Fig. 1/Fig. 2 (the patent gives no dimensions; sizes below are assumptions sized for a 1-lb ball).

  plow body   landside 520 x 15 x 150 mm on the ground (z = 0..150), share wedge in front, moldboard plate
  neck e      solid quarter bend, 120 mm diameter, rising from the landside to the beam axis (z = 450 mm)
  beam D      cast-iron barrel 1100 mm long, 130 -> 95 mm outside, 50 mm bore (a 1-lb iron ball is 49 mm)
              bore split into the chamber (first 150 mm, where the powder gas pushes at peak pressure) and the rest
  hole i      16 mm vertical clevis-bolt hole near the muzzle, where the team is hitched
Units mm.  python make_plow_gun.py
"""
import math
from pathlib import Path

import gmsh

OUT = Path(__file__).parent


def build():
    gmsh.model.add("plow_gun")
    occ = gmsh.model.occ
    # plow body
    landside = occ.addBox(0, -7.5, 0, 520, 15, 150)
    share = occ.addWedge(520, -7.5, 0, 160, 140, 40, ltx=0)          # point forward along +x, low and flat
    occ.rotate([(3, share)], 520, -7.5, 0, 0, 0, 1, 0)
    mold = occ.addBox(250, 7.5, 0, 300, 10, 140)
    occ.rotate([(3, mold)], 550, 7.5, 0, 0, 0, 1, math.radians(25))  # mold side flares out behind the share
    # neck: quarter circle R = 300 around (720, 0, 150), from (420, 0, 150) up to (720, 0, 450)
    c0 = occ.addPoint(420, 0, 150); cc = occ.addPoint(720, 0, 150); c1 = occ.addPoint(720, 0, 450)
    arc = occ.addCircleArc(c0, cc, c1)
    wire = occ.addWire([arc])
    disk = occ.addDisk(420, 0, 150, 65, 65, zAxis=[0, 0, 1])     # same radius as the breech: no step at the joint
    neck = occ.addPipe([(2, disk)], wire, "DiscreteTrihedron")
    # the 'frog': a solid block under the neck. On a 15 mm landside alone the 130 mm neck left sliver faces
    neck.append((3, occ.addBox(345, -70, 0, 150, 140, 155)))
    # beam D: tapered barrel with a bead at the muzzle, axis along +x at z = 450
    L = 1100
    barrel = occ.addCone(720, 0, 450, L, 0, 0, 65, 47.5)
    bead = occ.addCylinder(720 + L - 25, 0, 450, 25, 0, 0, 52)
    boss = occ.addCylinder(720 + L - 90, 0, 450 - 60, 0, 0, 120, 22)  # thickened metal round the clevis hole
    body = occ.fuse([(3, landside)], [(3, share), (3, mold)] + neck + [(3, barrel), (3, bead), (3, boss)])[0]
    # bore: chamber + rest (two cylinders so the chamber is its own face), clevis hole i, vent hole h
    breech = 760
    chamber = occ.addCylinder(breech, 0, 450, 150, 0, 0, 25)
    # the rest of the bore in four lengths: one 910 mm cylindrical face (18 diameters long) failed Gmsh's surface mesh
    rest, start = [], breech + 150
    seg = (720 + L - start) / 4
    for k in range(4):
        rest.append((3, occ.addCylinder(start + k * seg, 0, 450, seg + (1 if k == 3 else 0), 0, 0, 25)))
    # The clevis bolt passes through the barrel in the patent; here it is two 25 mm deep sockets in the bosses
    # above and below the bore (a through hole crossing the bore gave Gmsh overlapping facets). The vent hole h is
    # left out: 6 mm, no structural role.
    top = occ.addCylinder(720 + L - 90, 0, 450 + 60 - 25, 0, 0, 30, 8)
    bottom = occ.addCylinder(720 + L - 90, 0, 450 - 60 - 5, 0, 0, 30, 8)
    tool, _ = occ.fragment([(3, chamber)], rest)      # keep the internal seams so each length is its own face
    occ.cut(body, tool + [(3, top), (3, bottom)])
    occ.synchronize()
    gmsh.write(str(OUT / "plow_gun.step"))


if __name__ == "__main__":
    gmsh.initialize(["", "-nopopup"])
    gmsh.option.setNumber("General.Terminal", 0)
    try:
        build()
    finally:
        gmsh.finalize()
    print("ok", OUT / "plow_gun.step")
