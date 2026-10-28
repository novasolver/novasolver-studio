"""Studio 0.4 acceptance: shared history, geometry descriptors and shared face intent."""
from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from novastudio import commands as C, geometry, store
from novastudio.api import app
from novastudio.store import StudioError


@pytest.fixture(autouse=True)
def private_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv('NOVASTUDIO_WORKSPACE', str(tmp_path / 'cases_root'))


def edit(cid, changes, **kw):
    return C.update_case(cid, store.load(cid)['revision'], changes, **kw)


def undo(cid, redo=False):
    return C.undo_case(cid, store.load(cid)['revision'], redo=redo, lang='en')


def user_state(case):
    return {k: v for k, v in case.items() if k not in ('revision', 'provenance', 'checks')}


def test_undo_redo_and_mesh_staleness():
    case = C.create_case('cantilever')['case']
    cid = case['case_id']
    C.generate_mesh(cid)
    edit(cid, {'boundaries.y0.role': 'load'})
    edit(cid, {'boundaries.y0.force': '500 N'})
    edit(cid, {'geometry.params.length': '300 mm'})
    final = store.load(cid)
    assert geometry.mesh_state(final)['stale']
    rev = final['revision']
    for _ in range(3):
        p = undo(cid)
        assert not p['ui']['mesh']['state']['stale']
    assert store.load(cid)['revision'] == rev + 3
    assert user_state(store.load(cid)) == user_state(case)
    for _ in range(3):
        undo(cid, True)
    assert user_state(store.load(cid)) == user_state(final)
    assert geometry.mesh_state(store.load(cid))['stale']
    undo(cid)
    edit(cid, {'mesh.size': 'fine'})
    assert C.case_payload(cid)['history']['redo_count'] == 0


def test_coalescing(monkeypatch):
    cid = C.create_case('cantilever')['case']['case_id']
    now = store.time.time()
    monkeypatch.setattr(store.time, 'time', lambda: now)
    for i in range(5):
        edit(cid, {'boundaries.x1.force': f'{200+i} N'})
        now += .1
    assert len(store.history(cid)['undo']) == 1
    undo(cid)
    assert store.load(cid)['boundaries']['x1']['force']['value'] == 1000
    for v in (300, 400):
        edit(cid, {'boundaries.x1.force': f'{v} N'})
        now += 3
    assert len(store.history(cid)['undo']) == 2
    rev = store.load(cid)['revision']
    edit(cid, {'boundaries.x1.force': '400 N'})
    assert store.load(cid)['revision'] == rev


def test_mcp_source_and_undo():
    from novastudio import mcp_server as M
    c = C.create_case('cantilever')['case']
    r = asyncio.run(M.update_case(c['case_id'], c['revision'], {'boundaries.y0.role': 'fixed'}, language='en'))
    assert not r.is_error
    assert store.history(c['case_id'])['undo'][-1]['source'] == 'ai'
    r = asyncio.run(M.undo_change(c['case_id'], language='en'))
    assert not r.is_error and r.structured_content['undone']['summary']
    assert r.structured_content['undone']['source'] == 'ai'
    assert store.load(c['case_id'])['boundaries']['y0']['role'] == 'free'


def test_mcp_initial_changes_and_clone_history():
    from novastudio import mcp_server as M
    r = asyncio.run(M.create_case('cantilever', {'boundaries.y0.role': 'fixed'}, language='en'))
    assert not r.is_error
    cid = r.structured_content['case_id']
    assert store.history(cid)['undo'][-1]['source'] == 'ai'
    r = asyncio.run(M.clone_case(cid, {'boundaries.z0.role': 'fixed'}, language='en'))
    assert not r.is_error
    clone = r.structured_content['case_id']
    h = store.history(clone)
    assert len(h['undo']) == 1 and not h['redo']
    assert h['undo'][0]['source'] == 'ai' and h['undo'][0]['before']['case_id'] == clone
    undo(clone)
    assert store.load(clone)['boundaries']['y0']['role'] == 'fixed'
    assert store.load(clone)['boundaries']['z0']['role'] == 'free'


def test_empty_history_and_revision():
    c = C.create_case('cantilever')['case']
    for redo, key in ((False, 'err.nothing_to_undo'), (True, 'err.nothing_to_redo')):
        with pytest.raises(StudioError) as e:
            C.undo_case(c['case_id'], c['revision'], redo=redo)
        assert e.value.key == key and e.value.status == 409
    with pytest.raises(StudioError) as e:
        C.undo_case(c['case_id'], 0)
    assert e.value.key == 'err.revision'


def test_history_cap_and_no_coalescing_across_source_or_undo(monkeypatch):
    cid = C.create_case('cantilever')['case']['case_id']
    edit(cid, {'boundaries.x1.force': '1 N'}, source='gui')
    edit(cid, {'boundaries.x1.force': '2 N'}, source='ai')
    assert len(store.history(cid)['undo']) == 2
    undo(cid); undo(cid, True)
    edit(cid, {'boundaries.x1.force': '3 N'}, source='ai')
    assert len(store.history(cid)['undo']) == 3
    now = store.time.time()
    monkeypatch.setattr(store.time, 'time', lambda: now)
    for i in range(101):
        now += 3
        edit(cid, {'boundaries.x1.force': f'{10+i} N'})
    assert len(store.history(cid)['undo']) == 100


def make_shape(path, stl=False, fillet=True):
    import gmsh
    gmsh.initialize(['', '-nopopup'])
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        gmsh.model.add('faces')
        occ = gmsh.model.occ
        # File coordinates are mm. A rounded outside edge and a Z through-hole are independent features.
        box = occ.addBox(0, 0, 0, 40, 30, 20)
        occ.synchronize()
        edge = next(t for _,t in gmsh.model.getEntities(1) if
                    abs(occ.getCenterOfMass(1,t)[0]) < 1e-6 and abs(occ.getCenterOfMass(1,t)[1]) < 1e-6)
        rounded = occ.fillet([box], [edge], [2]) if fillet else [(3,box)]
        hole = occ.addCylinder(20, 15, -1, 0, 0, 22, 5)
        occ.cut(rounded, [(3,hole)])
        occ.synchronize()
        for _,tag in gmsh.model.getEntities(2):
            gmsh.model.setEntityName(2,tag, f'Part/Seat {tag}')
        if stl:
            gmsh.option.setNumber('Mesh.MeshSizeMax', 3)
            gmsh.option.setNumber('Mesh.MeshSizeFromCurvature', 24)
            gmsh.model.mesh.generate(2)
        gmsh.write(str(path))
    finally:
        gmsh.finalize()


@pytest.fixture
def imported(tmp_path):
    path = tmp_path / 'faces.step'
    make_shape(path)
    return C.import_geometry('structural', path.name, path=str(path), lang='en')['case']


def test_step_descriptors(imported):
    faces = imported['geometry']['faces']
    assert len(faces) == 8
    planes = [f for f in faces if f['type'] == 'Plane']
    assert len(planes) == 6
    for f in planes:
        normal = np.array(f['normal'])
        assert np.linalg.norm(normal) == pytest.approx(1)
        assert normal @ (np.array(f['centroid']) - [.02,.015,.01]) > 0
        label = C.face_label({}, f['key'], 'en', imported)
        assert 'mm²' in label and any(a in label for a in ('+X','-X','+Y','-Y','+Z','-Z')) or f.get('name')
        assert f['bbox'] and f['neighbors']
    hole = next(f for f in faces if f.get('radius',0) == pytest.approx(.005, rel=.01))
    assert abs(hole['axis'][2]) > .999
    assert np.linalg.norm(np.array(hole['axis_point'])[:2]-[.02,.015]) < .00005
    assert set(hole['neighbors']) == {f['key'] for f in planes if abs(f['normal'][2]) > .99}
    fillet = next(f for f in faces if f.get('radius',0) == pytest.approx(.002, rel=.01))
    assert set(fillet['smooth_neighbors']) == {f['key'] for f in planes if f['normal'][0] < -.99 or f['normal'][1] < -.99}
    assert 'R5' in C.face_label({}, hole['key'], 'en', imported) or hole.get('name')
    described = C.describe_case(imported['case_id'], lang='en')
    dh = next(f for f in described['faces'] if f['key'] == hole['key'])
    assert dh['radius_mm'] == pytest.approx(5, rel=.01)


def test_cad_names_when_writer_supports_them(imported):
    named = [f for f in imported['geometry']['faces'] if f.get('name','').startswith('Seat')]
    if not named:
        pytest.skip('Gmsh STEP writer does not preserve per-face entity labels')
    f = named[0]
    assert C.face_label({}, f['key'], 'en', imported).startswith(f['name'])


@pytest.mark.parametrize('fillet', [False, True])
def test_stl_descriptors(tmp_path, fillet):
    path = tmp_path / 'faces.stl'
    make_shape(path, True, fillet)
    c = C.import_geometry('thermal', path.name, path=str(path))['case']
    faces = c['geometry']['faces']
    assert len(faces) >= 6
    assert all(f['neighbors'] and 'smooth_neighbors' in f and f['bbox'] for f in faces)
    planes = [f for f in faces if f.get('normal')]
    # stl_face_groups merges the fillet with its two tangent planes into one curved group.
    assert len(planes) >= (4 if fillet else 6)
    assert all(np.array(f['normal']) @ (np.array(f['centroid'])-[.02,.015,.01]) > 0 for f in planes)


def test_groups():
    cid = C.create_case('cantilever')['case']['case_id']
    edit(cid, {'face_groups.seats': ['y0','z0']})
    edit(cid, {'boundaries.@seats.role': 'fixed'})
    assert all(store.load(cid)['boundaries'][k]['role'] == 'fixed' for k in ('y0','z0'))
    assert set(store.history(cid)['undo'][-1]['paths']) == {'boundaries.y0.role','boundaries.z0.role'}
    undo(cid)
    assert all(store.load(cid)['boundaries'][k]['role'] == 'free' for k in ('y0','z0'))
    with pytest.raises(StudioError) as e:
        edit(cid, {'boundaries.@missing.role': 'fixed'})
    assert e.value.key == 'err.unknown_group'
    with pytest.raises(StudioError) as e:
        edit(cid, {'face_groups.bad': ['missing']})
    assert e.value.key == 'err.group_members'
    edit(cid, {'face_groups.empty': []})
    rev = store.load(cid)['revision']
    edit(cid, {'boundaries.@empty.role': 'fixed'})
    assert store.load(cid)['revision'] == rev
    edit(cid, {'face_groups.seats': None, 'face_groups.renamed': ['y0','z0']})
    assert store.load(cid)['face_groups'] == {'renamed': ['y0','z0'], 'empty': []}
    undo(cid)
    assert 'seats' in store.load(cid)['face_groups']
    edit(cid, {'face_groups.Bolt.seat.001': ['z1']})
    edit(cid, {'boundaries.@Bolt.seat.001.role': 'fixed'})
    assert store.load(cid)['boundaries']['z1']['role'] == 'fixed'
    undo(cid)
    assert store.load(cid)['boundaries']['z1']['role'] == 'free'


def test_gui_selection_and_http_history():
    from novastudio import mcp_server as M
    client = TestClient(app, base_url='http://127.0.0.1')
    empty = asyncio.run(M.get_gui_selection(language='en'))
    assert not empty.is_error and 'No GUI selection' in empty.content[0].text
    c = C.create_case('cantilever')['case']
    cid = c['case_id']
    body = dict(case_id=cid, revision=c['revision'], step='boundaries', selected=['y0'], hidden=['z0'])
    assert client.put('/api/gui-state', json=body).status_code == 200
    r = asyncio.run(M.get_gui_selection(language='en')).structured_content
    assert r['case_id'] == cid and r['age_s'] < 5 and r['selected'][0]['key'] == 'y0'
    assert r['selected'][0]['label'] and r['selected'][0]['normal'] == [0,-1,0]
    assert r['selected'][0]['role'] == 'free'
    body['selected'] = []
    client.put('/api/gui-state', json=body)
    assert C.get_gui_selection('en')['message'] == 'Nothing is selected.'
    from novastudio.config import workspace
    path = workspace()/'.gui_state.json'
    state = json.loads(path.read_text(encoding='utf-8')); state['ts'] -= 1801
    store._write_json(path,state)
    assert '30 minutes' in C.get_gui_selection('en')['message']
    p = edit(cid, {'boundaries.y0.role': 'fixed'})
    r = client.post(f'/api/cases/{cid}/undo', json={'expected_revision': p['case']['revision']})
    assert r.status_code == 200 and r.json()['undone']['paths'] == ['boundaries.y0.role']
    r = client.post(f'/api/cases/{cid}/redo', json={'expected_revision': r.json()['case']['revision']})
    assert r.status_code == 200 and r.json()['case']['boundaries']['y0']['role'] == 'fixed'


def test_labelled_render(imported):
    cid = imported['case_id']
    png, front = C.render_view(cid, 'faces', 'en')
    back_png, back = C.render_view(cid, 'faces', 'en', view='iso_back')
    assert png.startswith(b'\x89PNG') and back_png.startswith(b'\x89PNG')
    assert set(front['labelled_faces']) | set(back['labelled_faces']) == {f['key'] for f in imported['geometry']['faces']}
    highlighted, _ = C.render_view(cid, 'faces', 'en', highlight=front['labelled_faces'][:1])
    assert highlighted != png
    for view in ('top','bottom','front','back','left','right'):
        picture, meta = C.render_view(cid, 'faces', 'en', view=view)
        assert picture.startswith(b'\x89PNG')
        if view in ('top', 'bottom'):
            sign = 1 if view == 'top' else -1
            expected = {f['key'] for f in imported['geometry']['faces'] if f.get('normal', [0,0,0])[2]*sign > .99}
            assert expected <= set(meta['labelled_faces'])
            hidden = {f['key'] for f in imported['geometry']['faces'] if f.get('normal', [0,0,0])[2]*sign < -.99}
            assert not hidden.intersection(meta['labelled_faces'])  # the opposite planar face is depth-occluded


def test_labels_and_names():
    case = {'geometry': {'kind': 'import', 'faces': [
        {'key': 'f1', 'n': 13, 'type': 'Plane', 'normal': [0,0,1], 'area': .0012},
        {'key': 'f2', 'n': 7, 'type': 'Cylinder', 'axis': [0,0,1], 'radius': .005},
        {'key': 'f3', 'n': 9, 'type': 'Plane', 'name': 'Bolt seat'},
    ]}}
    for lang in ('ja','en','zh'):
        label = C.face_label({}, 'f1', lang, case)
        assert '13' in label and '+Z' in label and '1,200' in label and 'mm²' in label
        assert 'R5' in C.face_label({}, 'f2', lang, case) and 'Z' in C.face_label({}, 'f2', lang, case)
        assert C.face_label({}, 'f3', lang, case).startswith('Bolt seat')


def test_readiness():
    cid = C.create_case('thermal-block')['case']['case_id']
    edit(cid, {'boundaries.x0.role': 'convection', 'boundaries.x1.role': 'convection'})
    assert 'uniform_temperature' in {i['code'] for i in C.validate_case(cid)['items']}
    edit(cid, {'boundaries.y0.role': 'heat-flux'})
    assert 'uniform_temperature' not in {i['code'] for i in C.validate_case(cid)['items']}
    edit(cid, {'boundaries.y0.flux': '0 W/m2'})
    assert 'uniform_temperature' in {i['code'] for i in C.validate_case(cid)['items']}
    edit(cid, {'boundaries.x0.tinf': '50 degC'})
    assert 'uniform_temperature' not in {i['code'] for i in C.validate_case(cid)['items']}
    cid = C.create_case('busbar')['case']['case_id']
    assert 'uniform_temperature' not in {i['code'] for i in C.validate_case(cid)['items']}
    edit(cid, {'boundaries.x0.voltage': '0 V'})
    assert 'uniform_temperature' in {i['code'] for i in C.validate_case(cid)['items']}
    edit(cid, {'physics.joule_heating': False})
    assert 'uniform_temperature' not in {i['code'] for i in C.validate_case(cid)['items']}


def test_old_case():
    c = C.create_case('cantilever')['case']
    c['geometry'].pop('faces', None)
    c.pop('face_groups', None)
    store.save(c, bump=False)
    cid = c['case_id']
    assert C.describe_case(cid)['face_groups'] == {}
    assert C.render_view(cid, 'faces', 'en')[0].startswith(b'\x89PNG')
    edit(cid, {'boundaries.y0.role': 'fixed'})
    undo(cid)
    assert user_state(store.load(cid)) == user_state(c)
    C.put_gui_state(dict(case_id=cid, revision=store.load(cid)['revision'], step='boundaries', selected=['y0'], hidden=[]))
    assert C.get_gui_selection('en')['selected'][0]['role'] == 'free'


def test_mcp_contract_and_i18n():
    from novastudio import mcp_server as M
    source = Path(M.__file__).read_text(encoding='utf-8')
    assert source.count('@mcp.tool(') == 23
    for fn in (M.undo_change, M.get_gui_selection, M.render_view):
        assert len(fn.__doc__) < 600
    root = Path(__file__).resolve().parents[2]
    bundle = (root/'make_mcpb.py').read_text(encoding='utf-8')
    assert 'tools/list' in bundle and 'manifest["tools"] = built_tools' in bundle
    for folder in ('backend/novastudio/i18n', 'frontend/src/i18n'):
        tables = [json.loads((root/folder/(lang+'.json')).read_text(encoding='utf-8')) for lang in ('ja','en','zh')]
        assert tables[0].keys() == tables[1].keys() == tables[2].keys()
