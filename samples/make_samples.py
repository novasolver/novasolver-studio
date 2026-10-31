"""Generate the sample CAD files shipped with Studio (STEP, units mm).  python samples/make_samples.py"""
from pathlib import Path

import gmsh

OUT = Path(__file__).parent


def bracket():
    gmsh.model.add("bracket")
    occ = gmsh.model.occ
    base = occ.addBox(0, 0, 0, 80, 40, 8)              # horizontal flange (bolted down)
    wall = occ.addBox(0, 0, 0, 8, 40, 60)              # vertical flange (loaded)
    occ.fuse([(3, base)], [(3, wall)])
    hole1 = occ.addCylinder(55, 20, -1, 0, 0, 10, 5)   # bolt hole in the base
    occ.cut(occ.getEntities(3), [(3, hole1)])
    occ.synchronize()
    gmsh.write(str(OUT / "l_bracket.step"))


def heatsink():
    gmsh.model.add("heatsink")
    occ = gmsh.model.occ
    parts = [(3, occ.addBox(0, 0, 0, 60, 40, 5))]     # base plate
    for i in range(6):
        parts.append((3, occ.addBox(3 + i * 10, 0, 5, 3, 40, 30)))   # fins
    occ.fuse(parts[:1], parts[1:])
    occ.synchronize()
    gmsh.write(str(OUT / "heatsink.step"))


def pipe_elbow():
    """Fluid volume of a 90-degree pipe bend: inlet disc at x = 0, outlet disc at y = 90 mm."""
    import math
    gmsh.model.add("pipe_elbow")
    occ = gmsh.model.occ
    r, R = 10, 30
    a = occ.addCylinder(0, 0, 0, 80, 0, 0, r)
    b = occ.addTorus(80, 30, 0, R, r, angle=math.pi / 2)
    occ.rotate([(3, b)], 80, 30, 0, 0, 0, 1, -math.pi / 2)      # bend from +x direction to +y direction
    c = occ.addCylinder(110, 30, 0, 0, 60, 0, r)
    occ.fuse([(3, a)], [(3, b), (3, c)])
    occ.synchronize()
    gmsh.write(str(OUT / "pipe_elbow.step"))


def sphere():
    """10 mm sphere at the origin - the classic external-flow drag benchmark."""
    gmsh.model.add("sphere")
    gmsh.model.occ.addSphere(0, 0, 0, 5)
    gmsh.model.occ.synchronize()
    gmsh.write(str(OUT / "sphere.step"))


def cold_plate():
    """Water-cooled aluminium plate: two bodies in one file (plate with a bore + the water filling the bore).
    Water flows along +x through a 6 mm channel; a heater sits on the top face."""
    gmsh.model.add("cold_plate")
    occ = gmsh.model.occ
    plate = occ.addBox(0, 0, 0, 80, 40, 10)
    water = occ.addCylinder(0, 20, 5, 80, 0, 0, 3)
    occ.fragment([(3, plate)], [(3, water)])            # plate gets the bore, water is the second body
    occ.synchronize()
    gmsh.write(str(OUT / "cold_plate.step"))


def wall_hook():
    """3D-printed wall hook as STL (what slicers and printables sites use): back plate with two screw holes, an arm
    and an upturned tip. The sharp inside corner at the arm root is where prints break: the sample shows it."""
    gmsh.model.add("wall_hook")
    occ = gmsh.model.occ
    plate = occ.addBox(0, 0, 0, 4, 30, 60)             # screwed to the wall at x = 0
    arm = occ.addBox(4, 7.5, 0, 36, 15, 6)
    tip = occ.addBox(34, 7.5, 6, 6, 15, 12)
    occ.fuse([(3, plate)], [(3, arm), (3, tip)])
    holes = [(3, occ.addCylinder(-1, 15, z, 6, 0, 0, 2.25)) for z in (20, 48)]
    occ.cut(occ.getEntities(3), holes)
    occ.synchronize()
    gmsh.option.setNumber("Mesh.MeshSizeMax", 2.0)
    gmsh.model.mesh.generate(2)
    gmsh.option.setNumber("Mesh.Binary", 1)
    gmsh.write(str(OUT / "wall_hook.stl"))


if __name__ == "__main__":
    gmsh.initialize(["", "-nopopup"])
    gmsh.option.setNumber("General.Terminal", 0)
    try:
        bracket()
        heatsink()
        pipe_elbow()
        sphere()
        cold_plate()
        wall_hook()
    finally:
        gmsh.finalize()
    print([p.name for p in OUT.glob("*.step")])
