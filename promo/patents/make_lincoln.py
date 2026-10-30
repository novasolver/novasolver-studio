"""US 6,469 (1849) Abraham Lincoln, 'Buoying vessels over shoals': one expansible buoyant chamber.

The patent gives no dimensions, so they are scaled from Fig. 1 against an Illinois-river steamboat of about 40 m:
the chamber is 9 m long and 1.5 m wide and expands to 1.2 m deep. Modelled is what carries the lift: the bottom h
(oak plank, 75 mm) and the four vertical spars D (oak, 150 mm square) that are 'permanently secured to the under
sides of the chambers' and slide up through the guard. The india-rubber sides and the top g carry no lift (the
openings m keep the air inside at atmospheric pressure) and are left out. Units mm.  python make_lincoln.py
"""
from pathlib import Path

import gmsh

OUT = Path(__file__).parent
L, W, T = 9000, 1500, 75            # bottom plank
S, H = 150, 3000                    # spar section and height above the plank
XS = [L / 8 + i * L / 4 for i in range(4)]   # four spars, 2.25 m apart, as in Fig. 1


def build():
    gmsh.model.add("lincoln")
    occ = gmsh.model.occ
    plank = occ.addBox(0, 0, 0, L, W, T)
    spars = [occ.addBox(x - S / 2, W / 2 - S / 2, T, S, S, H) for x in XS]
    occ.fuse([(3, plank)], [(3, s) for s in spars])
    occ.synchronize()
    gmsh.write(str(OUT / "lincoln_chamber.step"))


if __name__ == "__main__":
    gmsh.initialize(["", "-nopopup"])
    gmsh.option.setNumber("General.Terminal", 0)
    try:
        build()
    finally:
        gmsh.finalize()
    print("ok", OUT / "lincoln_chamber.step")
