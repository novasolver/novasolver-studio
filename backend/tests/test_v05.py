"""Studio 0.5 acceptance: closed-form answers, conservation, exports and the shared API/MCP contract."""
from __future__ import annotations

import asyncio
import json
import math
import os
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from novastudio import commands as C, fem_tet10 as fem, jobs, results, store, templates
from novastudio.store import StudioError


NEW = ('cantilever-modal', 'thermal-bar-fixed', 'thermal-bar-free', 'hanging-bar', 'rotating-disk', 'shaft-torsion')


@pytest.fixture(scope='module', autouse=True)
def private_workspace(tmp_path_factory):
    old = os.environ.get('NOVASTUDIO_WORKSPACE')
    os.environ['NOVASTUDIO_WORKSPACE'] = str(tmp_path_factory.mktemp('v05'))
    yield
    if old is None:
        os.environ.pop('NOVASTUDIO_WORKSPACE', None)
    else:
        os.environ['NOVASTUDIO_WORKSPACE'] = old


def solve(tid, changes=None, mode=None):
    p = C.create_case(tid, changes, lang='en')
    cid = p['case']['case_id']
    out = C.run_simulation(cid, mode=mode, wait_s=1, lang='en')
    jid = out['job']['job_id']
    j = jobs.wait(jid, 1800)
    assert j['state'] == 'done', C.job_status(jid, 'en')
    jd, raw = results.load(cid)
    assert raw['converged'], raw
    return cid, jd, raw


@pytest.fixture(scope='module', params=NEW)
def benchmark(request):
    return request.param, solve(request.param)


def measure(name, value, reference, tolerance):
    print(f'MEASURE {name}: computed={value:.12g}, reference={reference:.12g}, error_pct={(value/reference-1)*100:.9g}', flush=True)
    assert value == pytest.approx(reference, rel=tolerance)


def test_01_default_templates_and_verification(benchmark):
    tid, (cid, jd, r) = benchmark
    assert r['reference']['applicable'] and r['reference']['pass'], r['reference']
    assert C.verify_case(cid)['gates']['verified']
    for lang in ('ja','en','zh'):
        listed = {v['id']: v for v in C.list_templates(lang)['templates']}
        assert set(NEW) <= set(listed)
        assert not listed[tid]['title'].startswith('template.')
        assert C.get_results(cid, lang=lang)['quantities']
    data, mesh = np.load(jd/'results.npz'), np.load(jd/'mesh.npz')
    m = r['metrics']
    if tid == 'cantilever-modal':
        measure('modal_f1_Hz', r['modes'][0]['frequency_hz'], 206.4, .02)
        measure('modal_f2_Hz', r['modes'][2]['frequency_hz'], 1293., .02)
        mass = fem.mass_matrix(mesh['nodes'], mesh['tets'], 7850.)
        phi = data['phi'].reshape(len(r['modes']), -1).T
        np.testing.assert_allclose(phi.T@(mass@phi), np.eye(len(r['modes'])), atol=1e-8, rtol=0)
        np.testing.assert_allclose(np.linalg.norm(data['mode_shapes'],axis=2).max(1), 1, atol=1e-12)
        assert C.get_results(cid)['modes'] == r['modes']
        assert C.field(cid, 'mode', mode=3)['mode'] == 3
        png, _ = C.render_view(cid, 'mode', mode=3)
        assert png.startswith(b'\x89PNG')
    elif tid == 'thermal-bar-fixed':
        measure('fixed_thermal_stress_Pa', m['thermal_stress_pa'], 246e6, .02)
    elif tid == 'thermal-bar-free':
        measure('free_elongation_m', m['elongation_m'], .00012, .01)
        assert np.abs(data['s']).max() < .01*246e6
    elif tid == 'hanging-bar':
        measure('hanging_top_stress_Pa', m['top_stress_pa'],7850*9.81,.02)
        measure('hanging_tip_m',m['tip_disp_m'],7850*9.81/(2*205e9),.02)
    elif tid == 'rotating-disk':
        measure('rotating_centre_Pa',m['center_stress_pa'],3.3/8*7850*(10000*np.pi/30)**2*.1**2,.02)
    elif tid == 'shaft-torsion':
        measure('torsion_shear_Pa',m['shear_pa'],16*100/(np.pi*.02**3),.02)
        measure('torsion_twist_rad',m['twist_rad'],100*.2/((205e9/2.6)*(np.pi*.02**4/32)),.02)


def test_02_free_free_has_no_rigid_modes():
    cid,jd,r = solve('cantilever-modal', {'boundaries.x0.role':'free', 'physics.modes':8})
    assert r['free_free'] and len(r['modes']) == 8
    # Free-free first elastic bending root is beta L = 4.73004 (not the clamped root).
    ref = 4.7300407449**2/(2*np.pi)*np.sqrt(205e9*.01**2/(12*7850*.2**4))
    measure('free_free_f1_Hz',r['modes'][0]['frequency_hz'],ref,.02)
    assert all(v['frequency_hz'] > .001*ref for v in r['modes'])
    assert any(w['code'] == 'free_free' for w in C.get_results(cid)['warnings'])


def test_03_coupled_linear_temperature_and_expansion():
    cid,jd,r = solve('thermal-bar-free', {'physics.thermal_load.mode':'solve', 'physics.T_ref':'0 degC',
        'boundaries.x0.thermal.role':'temperature','boundaries.x0.thermal.temperature':'0 degC',
        'boundaries.x1.thermal.role':'temperature','boundaries.x1.thermal.temperature':'100 degC'})
    mesh,data = np.load(jd/'mesh.npz'),np.load(jd/'results.npz')
    np.testing.assert_allclose(data['T'],273.15+100*mesh['nodes'][:,0]/.1,atol=1e-6,rtol=0)
    end = np.unique(mesh['face_x1'])
    measure('coupled_elongation_m',data['u'][end,0].mean(),12e-6*50*.1,.01)
    assert 'temp' in [q['id'] for q in C.get_results(cid)['quantities']]


@pytest.mark.parametrize('role', ['moment','remote-force','bearing'])
def test_04_face_resultants_and_reactions(role):
    from novastudio.structural import face_load
    from novastudio.run_worker import structural_loads, symmetry_rollers
    from novastudio import geometry
    tid, face = ('shaft-torsion','z1') if role != 'bearing' else ('coax','inner')
    c = store.create(tid)
    if role == 'bearing':
        c['physics'] = {'kind':'linear-static'}
        c['boundaries'] = {f:{'role':'fixed' if f == 'z0' else 'free'} for f in ('inner','outer','z0','z1')}
    b = {'role':role, 'direction':'+z' if role == 'moment' else '+x'}
    if role == 'moment':
        b['torque'] = {'value':100,'unit':'N-m'}
    else:
        b['force'] = {'value':123,'unit':'N'}
    if role == 'remote-force':
        b['point'] = {'value':[0,25,230],'unit':'mm'}
    c['boundaries'][face] = b
    geometry.generate_mesh(c)
    mesh = dict(np.load(geometry.mesh_dir(c)/'mesh.npz'))
    nodes,tri = mesh['nodes'],mesh['face_'+face]
    f = fem.surface_forces(nodes,[(tri,face_load(c,face,nodes,tri,b))])
    expected_force = np.zeros(3) if role == 'moment' else np.array([123.,0,0])
    np.testing.assert_allclose(f.sum(0),expected_force,atol=1e-6,rtol=0)
    torque = np.cross(nodes,f).sum(0)
    if role == 'moment':
        np.testing.assert_allclose(torque,[0,0,100],atol=1e-6,rtol=0)
    if role == 'remote-force':
        np.testing.assert_allclose(torque,np.cross([0,.025,.230],expected_force),atol=1e-6,rtol=0)
    fixed, tractions = structural_loads(c,mesh)
    r = fem.solve(nodes,mesh['tets'],205e9,.3,fixed,tractions,rollers=symmetry_rollers(c,mesh))
    np.testing.assert_allclose(r['reaction']+expected_force,0,atol=1e-6,rtol=0)
    np.testing.assert_allclose(r['reaction_moment']+torque,0,atol=1e-6,rtol=0)


def test_05_bearing_refuses_missing_axis():
    from novastudio.structural import face_load
    c = templates.new_case('cantilever','c_test')
    with pytest.raises(StudioError,match='err.bearing_axis'):
        face_load(c,'x0',np.zeros((6,3)),np.arange(6).reshape(1,6),{'role':'bearing','force':1,'direction':'+x'})


def test_06_export_results(benchmark):
    import csv
    import meshio
    tid,(cid,jd,r) = benchmark
    path = Path(C.export_results(cid,'vtu',lang='en')['path'])
    xml = ET.parse(path).getroot()
    assert xml.attrib['type'] == 'UnstructuredGrid'
    read = meshio.read(path)
    mesh,data = np.load(jd/'mesh.npz'),np.load(jd/'results.npz')
    assert len(read.points) == len(mesh['nodes'])
    assert read.cells[0].type == 'tetra10' and len(read.cells[0].data) == len(mesh['tets'])
    if r['kind'] == 'modal':
        assert {'mode_1','phi_1'} <= set(read.point_data)
    else:
        assert {'u','vm','s'} <= set(read.point_data)
    csvpath = Path(C.export_results(cid,'csv',lang='en')['path'])
    with csvpath.open(newline='',encoding='utf-8') as fh:
        rows = list(csv.reader(fh))
    if r['kind'] == 'modal':
        assert rows[0][0:2] == ['mode','frequency_hz'] and len(rows) == len(r['modes'])+1
    else:
        assert rows[0][:4] == ['node','x_m','y_m','z_m'] and len(rows) == len(mesh['nodes'])+1
    report = Path(C.export_results(cid,'report',lang='en')['path']).read_text(encoding='utf-8')
    assert all(s in report for s in ('ran','converged','verified','reference','data:image/png;base64,'))
    assert str(Path.home()) not in report and str(Path.home()).replace('\\','/') not in report
    assert 'NovaSolver Studio' in report
    if tid == 'cantilever-modal':
        from fastapi.testclient import TestClient
        from novastudio.api import app
        from novastudio import mcp_server
        response = TestClient(app,base_url='http://127.0.0.1').get(f'/api/cases/{cid}/export?format=csv&lang=en')
        assert response.status_code == 200 and response.text.startswith('mode,frequency_hz,')
        assert 'attachment' in response.headers['content-disposition']
        tool = asyncio.run(mcp_server.export_results(cid,'vtu',language='en'))
        assert not tool.is_error and Path(tool.structured_content['path']).is_file()


def test_07_validation_and_i18n():
    from novastudio import units
    assert units.to_si('100 N·m') == 100
    assert units.to_si('100 N·mm') == .1
    c = templates.new_case('cantilever-modal','c_test')
    for path,value in [('physics.modes',0),('physics.modes',31),('materials.solid.alpha',-1),
                       ('physics.rotation.rpm',float('nan')),('physics.gravity.direction',[0,0,0])]:
        with pytest.raises(StudioError):
            store.apply_changes(c,{path:value})
    c,_ = store.apply_changes(c,{'materials.solid.alpha':0})
    assert c['materials']['solid']['alpha']['value'] == 0
    for root in (Path(templates.__file__).parent/'i18n',Path(__file__).resolve().parents[2]/'frontend/src/i18n'):
        sets = [set(json.loads((root/(lang+'.json')).read_text(encoding='utf-8'))) for lang in ('ja','en','zh')]
        assert sets[0] == sets[1] == sets[2]


def test_08_mcp_tool_count():
    from novastudio import mcp_server
    tools = asyncio.run(mcp_server.mcp.list_tools())
    assert len(tools) == 24
    assert 'export_results' in {t.name for t in tools}


def test_09_calculix_modal_when_available():
    from novastudio.config import find_calculix
    if not find_calculix():
        pytest.skip('CalculiX not installed')
    _,_,builtin = solve('cantilever-modal')
    _,_,ccx = solve('cantilever-modal',mode='final')
    measure('ccx_f1_Hz',ccx['modes'][0]['frequency_hz'],builtin['modes'][0]['frequency_hz'],.02)


def test_10_section_cap_and_line_probe(benchmark):
    tid,(cid,jd,r) = benchmark
    mesh = np.load(jd/'mesh.npz')
    q = 'mode' if r['kind'] == 'modal' else 'uz'
    section = {'normal':[1,0,0], 'position':.47}
    field = C.field(cid,q,section=section)
    points = np.asarray(field['positions']).reshape(-1,3)
    cut = mesh['nodes'][:,0].min()+.47*np.ptp(mesh['nodes'][:,0])
    assert points[:,0].max() <= cut+1e-8
    cap = np.abs(points[:,0]-cut) < 1e-8
    assert cap.sum() > 10 and np.isfinite(np.asarray(field['scalars'])[cap]).all()
    assert len(field['displacement']) == len(field['positions'])
    # This point is on the cut and inside the part, independent of the mesh's surface triangles.
    if tid not in ('shaft-torsion','rotating-disk'):
        lo,hi = mesh['nodes'].min(0),mesh['nodes'].max(0)
        a,b = (lo+hi)/2,(lo+hi)/2
        a[0],b[0] = lo[0],hi[0]
        line = C.probe_results(cid,line={'from':(a*1000).tolist(),'to':(b*1000).tolist(),'n':11})
        assert line['line']['inside_fraction'] == 1
        assert len(line['line']['samples']) == 11
    with pytest.raises(StudioError):
        C.field(cid,q,section={'normal':[0,0,0],'position':.5})


def test_11_mass_and_lobpcg_branch(monkeypatch):
    from test_memory_2026_10_28 import block_mesh
    corners = np.array([[0,0,0],[1,0,0],[0,1,0],[0,0,1]],float)
    single = np.vstack([corners,(corners[fem.EDGES[:,0]]+corners[fem.EDGES[:,1]])/2])
    exact = fem.mass_matrix(single,np.arange(10)[None],1.)
    volume = 1/6
    assert exact[0,0] == pytest.approx(volume/70,rel=1e-12)
    assert exact[0,3] == pytest.approx(volume/420,rel=1e-12)
    assert exact[0,12] == pytest.approx(-volume/105,rel=1e-12)
    nodes,tets,x0,_,_ = block_mesh(n=2,L=(.04,.02,.02))
    mass = fem.mass_matrix(nodes,tets,7850.)
    for axis in range(3):
        translation = np.zeros(3*len(nodes)); translation[axis::3] = 1
        assert translation@(mass@translation) == pytest.approx(7850*.04*.02*.02,rel=1e-12)
    assert np.linalg.eigvalsh(mass[:30,:30].toarray()).min() > 0
    direct = fem.solve_modal(nodes,tets,205e9,.3,7850.,[x0],modes=2)
    monkeypatch.setattr(fem,'MODAL_DIRECT_LIMIT',0)
    iterative = fem.solve_modal(nodes,tets,205e9,.3,7850.,[x0],modes=2)
    assert iterative['converged'],iterative
    np.testing.assert_allclose([m['frequency_hz'] for m in iterative['modes']],
                               [m['frequency_hz'] for m in direct['modes']],rtol=1e-5)


def test_12_bearing_pressure_is_cosine(monkeypatch):
    from novastudio import structural
    theta = np.deg2rad([-60,-30,0,30,60,180])
    points = np.column_stack([np.cos(theta),np.sin(theta),np.zeros(6)])
    # Six independent quadrature samples let us observe the pressure, separately from the resultant check.
    monkeypatch.setattr(structural,'surface_rule',lambda *_:(points[None],np.ones((1,6)),np.eye(6)))
    c = {'geometry':{'faces':[{'key':'hole','type':'Cylinder','axis':[0,0,1],'axis_point':[0,0,0],'radius':1}]}}
    forces = structural.face_load(c,'hole',points,np.arange(6)[None],{'role':'bearing','force':10.,'direction':'+x'})[0]
    pressure = np.einsum('ij,ij->i',forces,points)
    np.testing.assert_allclose(pressure[:5]/np.cos(theta[:5]),pressure[2],rtol=1e-12)
    np.testing.assert_allclose(forces.sum(0),[10,0,0],atol=1e-12)
    assert pressure[-1] == 0
