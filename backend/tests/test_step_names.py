"""CAD face names from STEP files (gmsh reads only the names of whole shapes)."""
import re

import numpy as np
import pytest

from novastudio import commands as C
from novastudio import step_names


@pytest.fixture(autouse=True)
def _workspace(tmp_path, monkeypatch):
    monkeypatch.setenv('NOVASTUDIO_WORKSPACE', str(tmp_path / 'ws'))


def plate_with_hole(path, two_bodies=False):
    """A 40x20x10 mm plate with a 8 mm hole (and optionally a touching block), written by OCCT through gmsh."""
    import gmsh
    gmsh.initialize()
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        box = gmsh.model.occ.addBox(0, 0, 0, 40, 20, 10)
        hole = gmsh.model.occ.addCylinder(20, 10, -1, 0, 0, 12, 4)
        gmsh.model.occ.cut([(3, box)], [(3, hole)])
        if two_bodies:
            gmsh.model.occ.addBox(40, 0, 0, 10, 20, 10)
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    return path


def name_faces(path, namer):
    """Give ADVANCED_FACEs names the way CAD writes them: namer(surface type, entity text) -> name or None."""
    txt = path.read_text(encoding='latin-1')
    ents = dict(re.findall(r"#(\d+)\s*=\s*([A-Z_]+)\(", txt))

    def sub(m):
        name = namer(ents.get(m.group(3)), m.group(0))
        return m.group(0) if name is None else f"#{m.group(1)} = ADVANCED_FACE('{name}',{m.group(2)},#{m.group(3)},"
    txt = re.sub(r"#(\d+) = ADVANCED_FACE\(''\s*,(\([^)]*\)),#(\d+),", sub, txt)
    path.write_text(txt, encoding='latin-1')
    return path


def test_decode_iso_10303_21_strings():
    assert step_names._decode("\\X2\\7A74\\X0\\") == '穴'                      # how CAD writes Japanese
    assert step_names._decode("Ma\\X\\DF") == 'Maß'
    ents = step_names.parse("DATA;\n#1=ADVANCED_FACE('it''s; fine',(#2),#3,.T.);\n#2=(A(1.) B('x',(1.,2.)));\nENDSEC;")
    assert ents.get(1) == [('ADVANCED_FACE', ["it's; fine", [('#', 2)], ('#', 3), '.T.'])]
    assert [t for t, _ in ents.get(2)] == ['A', 'B']


def test_imported_face_names_reach_the_case(tmp_path):
    p = name_faces(plate_with_hole(tmp_path / 'named.step'),
                   lambda surf, _: '\\X2\\7A74\\X0\\' if surf == 'CYLINDRICAL_SURFACE' else None)
    c = C.import_geometry('structural', p.name, path=str(p))['case']
    named = [f for f in c['geometry']['faces'] if f.get('name')]
    assert [f['name'] for f in named] == ['穴'] and named[0]['type'] == 'Cylinder'
    label = C.face_descriptor(c, named[0], 'ja')['label']
    assert '穴' in label


def test_every_face_and_both_touching_bodies(tmp_path):
    """Two bodies share the face at x = 40: their two coincident faces have the same vertices and type, and are told
    apart by the body they belong to. Every face comes back with its own name."""
    import gmsh
    p = name_faces(plate_with_hole(tmp_path / 'two.step', two_bodies=True),
                   lambda surf, s: 'F' + re.match(r'#(\d+)', s).group(1))
    text = p.read_text(encoding='latin-1')
    gmsh.initialize()
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        gmsh.option.setString('Geometry.OCCTargetUnit', 'M')
        gmsh.model.occ.importShapes(str(p))
        gmsh.model.occ.synchronize()
        faces, vols = step_names.gmsh_topology(gmsh)
        names = step_names.match(text, faces, vols)
        assert len(names) == len(faces) == 13 and len(set(names.values())) == 13
        at_x40 = [t for t in faces if np.allclose(faces[t][0][:, 0], 0.04)]
        assert len(at_x40) == 2 and names[at_x40[0]] != names[at_x40[1]]
    finally:
        gmsh.finalize()


def test_assembly_placement_and_unit(tmp_path):
    """A part placed in an assembly by ITEM_DEFINED_TRANSFORMATION, in inches: the vertices are moved and scaled
    before matching."""
    text = ASSEMBLY
    faces = {1: (np.array([[0.0254 * 10 + 0, 0, 0], [0.0254 * 10 + 0.0254, 0, 0], [0.0254 * 10, 0.0254, 0]]),
                 'Plane', [1])}
    assert step_names.match(text, faces, {1: faces[1][0]}) == {1: 'Seat'}
    faces = {1: (faces[1][0] + [1, 0, 0], 'Plane', [1])}                    # elsewhere: no name rather than a wrong one
    assert step_names.match(text, faces, {1: faces[1][0]}) == {}


def test_faces_with_the_same_vertices_are_told_apart_by_their_arcs():
    """Two half discs share both vertices, the straight edge and the plane (as the two halves of a split cylinder
    do): only the arcs differ, and each face gets its own name."""
    v = np.array([[1e-3, 0, 0], [-1e-3, 0, 0]])
    faces = {1: (v, 'Plane', [1], np.array([[0, 1e-3, 0], [0, 0, 0]])),
             2: (v, 'Plane', [1], np.array([[0, -1e-3, 0], [0, 0, 0]]))}
    assert step_names.match(HALVES, faces, {1: v}) == {1: 'upper', 2: 'lower'}


ASSEMBLY = """ISO-10303-21;
DATA;
#1=CARTESIAN_POINT('',(0.,0.,0.));
#2=CARTESIAN_POINT('',(1.,0.,0.));
#3=CARTESIAN_POINT('',(0.,1.,0.));
#4=VERTEX_POINT('',#1);
#5=VERTEX_POINT('',#2);
#6=VERTEX_POINT('',#3);
#7=EDGE_CURVE('',#4,#5,#90,.T.);
#8=EDGE_CURVE('',#5,#6,#90,.T.);
#9=EDGE_CURVE('',#6,#4,#90,.T.);
#10=ORIENTED_EDGE('',*,*,#7,.T.);
#11=ORIENTED_EDGE('',*,*,#8,.T.);
#12=ORIENTED_EDGE('',*,*,#9,.T.);
#13=EDGE_LOOP('',(#10,#11,#12));
#14=FACE_OUTER_BOUND('',#13,.T.);
#15=ADVANCED_FACE('Seat',(#14),#91,.T.);
#16=CLOSED_SHELL('',(#15));
#17=MANIFOLD_SOLID_BREP('part',#16);
#18=ADVANCED_BREP_SHAPE_REPRESENTATION('',(#17,#40),#99);
#19=SHAPE_REPRESENTATION('',(#40),#99);
#20=SHAPE_REPRESENTATION_RELATIONSHIP('','',#19,#18);
#30=SHAPE_REPRESENTATION('assembly',(#41,#42),#99);
#31=ITEM_DEFINED_TRANSFORMATION('','',#40,#42);
#32=(REPRESENTATION_RELATIONSHIP('','',#19,#30)REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION(#31)SHAPE_REPRESENTATION_RELATIONSHIP());
#40=AXIS2_PLACEMENT_3D('',#1,$,$);
#41=AXIS2_PLACEMENT_3D('',#1,$,$);
#43=CARTESIAN_POINT('',(10.,0.,0.));
#42=AXIS2_PLACEMENT_3D('',#43,$,$);
#90=LINE('',#1,$);
#91=PLANE('',#41);
#99=( LENGTH_UNIT() NAMED_UNIT(*) CONVERSION_BASED_UNIT('INCH',#98) );
ENDSEC;
END-ISO-10303-21;
"""


HALVES = """ISO-10303-21;
DATA;
#1=CARTESIAN_POINT('',(1.,0.,0.));
#2=CARTESIAN_POINT('',(-1.,0.,0.));
#3=CARTESIAN_POINT('',(0.,0.,0.));
#4=VERTEX_POINT('',#1);
#5=VERTEX_POINT('',#2);
#6=DIRECTION('',(0.,0.,1.));
#7=DIRECTION('',(1.,0.,0.));
#8=AXIS2_PLACEMENT_3D('',#3,#6,#7);
#9=CIRCLE('',#8,1.);
#10=LINE('',#1,$);
#11=EDGE_CURVE('',#4,#5,#9,.T.);
#12=EDGE_CURVE('',#5,#4,#9,.T.);
#13=EDGE_CURVE('',#4,#5,#10,.T.);
#14=EDGE_LOOP('',(#20,#22));
#15=EDGE_LOOP('',(#21,#22));
#20=ORIENTED_EDGE('',*,*,#11,.T.);
#21=ORIENTED_EDGE('',*,*,#12,.T.);
#22=ORIENTED_EDGE('',*,*,#13,.F.);
#30=FACE_OUTER_BOUND('',#14,.T.);
#31=FACE_OUTER_BOUND('',#15,.T.);
#32=PLANE('',#8);
#33=ADVANCED_FACE('upper',(#30),#32,.T.);
#34=ADVANCED_FACE('lower',(#31),#32,.F.);
#35=CLOSED_SHELL('',(#33,#34));
#36=MANIFOLD_SOLID_BREP('',#35);
#37=ADVANCED_BREP_SHAPE_REPRESENTATION('',(#36),#99);
ENDSEC;
END-ISO-10303-21;
"""
