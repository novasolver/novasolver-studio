"""CAD for the promotional analyses (STEP, units mm).  python samples/promo/make_promo.py

1. gpu_cold_plate.step   copper cold plate for a 700 W GPU: water body (Z-flow manifolds + 6 microchannels) and plate
2. ev_busbar.step        copper busbar bolted to a battery terminal block (two bodies sharing the contact face)
3. shelf.step            steel storage rack, four uprights and four shelves (one body)
"""
from pathlib import Path

import gmsh

OUT = Path(__file__).parent


def gpu_cold_plate(channels=6):
    """Plate 60 x 60 x 8 mm with a 30 x 30 mm die pad on top. Water enters at y = 0, spreads along the inlet
    manifold, crosses the plate through the channels under the die, and leaves at y = 60 (Z-flow)."""
    gmsh.model.add("gpu_cold_plate")
    occ = gmsh.model.occ
    plate = occ.addBox(0, 0, 0, 60, 60, 8)
    pad = occ.addBox(15, 15, 8, 30, 30, 1)
    occ.fuse([(3, plate)], [(3, pad)])
    water = [occ.addBox(4, 0, 2, 10, 56, 4),            # inlet port + inlet manifold (x 4-14)
             occ.addBox(46, 4, 2, 10, 56, 4)]           # outlet manifold + outlet port (x 46-56)
    pitch = 48 / channels
    for i in range(channels):
        y = 6 + pitch * (i + 0.5) - 1.5
        water.append(occ.addBox(14, y, 2, 32, 3, 4))   # 3 x 4 mm channel under the die
    w, _ = occ.fuse([(3, water[0])], [(3, t) for t in water[1:]])
    occ.fragment(occ.getEntities(3)[:1], w)            # plate gets the cavity, water is the second body
    occ.removeAllDuplicates()
    occ.synchronize()
    gmsh.write(str(OUT / "gpu_cold_plate.step"))


def ev_busbar():
    """A 60 x 20 x 3 mm copper busbar bolted onto an aluminium terminal block (lap joint 20 x 20 mm).
    Current enters at the free end of the bar and leaves through the bottom of the block."""
    gmsh.model.add("ev_busbar")
    occ = gmsh.model.occ
    block = occ.addBox(0, 0, 0, 20, 20, 15)
    bar = occ.addBox(0, 0, 15, 60, 20, 3)
    hole = occ.addCylinder(10, 10, -1, 0, 0, 20, 3.25)  # M6 clearance through both parts
    occ.cut([(3, block), (3, bar)], [(3, hole)], removeTool=True)
    occ.fragment(occ.getEntities(3), [])
    occ.removeAllDuplicates()
    occ.synchronize()
    gmsh.write(str(OUT / "ev_busbar.step"))


def ev_busbar_joint(layer=0.2):
    """The same lap joint with a 0.2 mm layer between bar and block standing for the contact resistance of the
    bolted joint (its conductivity is set per case: a tight joint ~10 uOhm, a loose one ~200 uOhm)."""
    gmsh.model.add("ev_busbar_joint")
    occ = gmsh.model.occ
    block = occ.addBox(0, 0, 0, 20, 20, 15)
    film = occ.addBox(0, 0, 15, 20, 20, layer)
    bar = occ.addBox(0, 0, 15 + layer, 60, 20, 3)
    hole = occ.addCylinder(10, 10, -1, 0, 0, 25, 3.25)
    occ.cut([(3, block), (3, film), (3, bar)], [(3, hole)], removeTool=True)
    occ.fragment(occ.getEntities(3), [])
    occ.removeAllDuplicates()
    occ.synchronize()
    gmsh.write(str(OUT / "ev_busbar_joint.step"))


def shelf(levels=4):
    """Steel rack 900 x 450 x 1800 mm: 40 x 40 mm uprights, 12 mm shelves (one welded body)."""
    gmsh.model.add("shelf")
    occ = gmsh.model.occ
    W, D, H, a, t = 900, 450, 1800, 40, 12
    parts = [occ.addBox(x, y, 0, a, a, H) for x in (0, W - a) for y in (0, D - a)]
    for i in range(levels):
        z = 150 + i * (H - 150 - t) / (levels - 1)
        parts.append(occ.addBox(0, 0, z, W, D, t))
    occ.fuse([(3, parts[0])], [(3, p) for p in parts[1:]])
    occ.synchronize()
    gmsh.write(str(OUT / "shelf.step"))


if __name__ == "__main__":
    gmsh.initialize(["", "-nopopup"])
    gmsh.option.setNumber("General.Terminal", 0)
    try:
        gpu_cold_plate()
        ev_busbar()
        ev_busbar_joint()
        shelf()
    finally:
        gmsh.finalize()
    print(sorted(p.name for p in OUT.glob("*.step")))
