"""STL import: a fillet blends tangentially into its planes, so the feature angle alone made one face of them."""
import gmsh
import pytest

from novastudio import commands as C


def _stl(path, all_edges):
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        b = gmsh.model.occ.addBox(0, 0, 0, 60, 30, 10)
        gmsh.model.occ.synchronize()
        edges = [c for _, c in gmsh.model.getEntities(1)]
        if not all_edges:                                    # the four vertical edges, then a through hole
            edges = [c for c in edges if gmsh.model.getBoundingBox(1, c)[5] - gmsh.model.getBoundingBox(1, c)[2] > 9]
        f = gmsh.model.occ.fillet([b], edges, [3 if all_edges else 5])
        if not all_edges:
            gmsh.model.occ.cut(f, [(3, gmsh.model.occ.addCylinder(30, 15, -1, 0, 0, 12, 5))])
        gmsh.model.occ.synchronize()
        gmsh.option.setNumber("Mesh.MeshSizeMax", 1.5)
        gmsh.model.mesh.generate(2)
        gmsh.write(str(path))
    finally:
        gmsh.finalize()


def test_filleted_plate_keeps_its_cad_faces(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVASTUDIO_WORKSPACE", str(tmp_path / "ws"))
    _stl(tmp_path / "plate.stl", all_edges=False)
    faces = C.import_geometry("structural", "plate.stl", path=str(tmp_path / "plate.stl"))["case"]["geometry"]["faces"]
    areas = sorted(round(f["area"] * 1e6) for f in faces)            # mm2
    # 4 quarter-cylinder fillets, 2 + 2 sides, the hole, top and bottom: the 11 faces of the CAD part
    assert areas == [78, 78, 78, 78, 200, 200, 313, 500, 500, 1700, 1700]


def test_fully_rounded_block_separates_its_planes(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVASTUDIO_WORKSPACE", str(tmp_path / "ws"))
    _stl(tmp_path / "block.stl", all_edges=True)
    faces = C.import_geometry("structural", "block.stl", path=str(tmp_path / "block.stl"))["case"]["geometry"]["faces"]
    planes = sorted(round(f["area"] * 1e6) for f in faces if f.get("type") == "Plane")
    assert planes == pytest.approx([24 * 4, 24 * 4, 54 * 4, 54 * 4, 54 * 24, 54 * 24], abs=2)   # box less r = 3
    assert len(faces) == 7                                           # the rounded edges and corners stay one face