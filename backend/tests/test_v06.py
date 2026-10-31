"""0.6 acceptance: actual FE responses and independent constitutive/tangent checks."""
from __future__ import annotations

import numpy as np
import pytest
import os
import json
import asyncio
import time
from pathlib import Path

from novastudio import fem_tet10 as fem, fem_nonlinear as nl, templates
from novastudio.box_mesh import generate
from novastudio import commands as C, store, results, geometry
from novastudio.contact import split_mesh
from novastudio.run_worker import structural_loads,symmetry_rollers
from novastudio.store import StudioError


NEW = ('press-fit','stacked-blocks','friction-block','large-cantilever','plastic-bar','plastic-beam-collapse','rubber-tension')


@pytest.fixture(scope='module',autouse=True)
def private_workspace(tmp_path_factory):
    old = os.environ.get('NOVASTUDIO_WORKSPACE')
    os.environ['NOVASTUDIO_WORKSPACE'] = str(tmp_path_factory.mktemp('v06'))
    yield
    if old is None:
        os.environ.pop('NOVASTUDIO_WORKSPACE',None)
    else:
        os.environ['NOVASTUDIO_WORKSPACE'] = old


_solved = {}


def solve_template(tid,changes=None):
    from novastudio import commands as C,jobs,results
    key = (tid,json.dumps(changes,sort_keys=True))
    if key in _solved:
        return _solved[key]
    p = C.create_case(tid,changes,lang='en'); cid = p['case']['case_id']
    started = time.perf_counter()
    out = C.run_simulation(cid,wait_s=1,lang='en'); jid = out['job']['job_id']
    j = jobs.wait(jid,1800)
    assert j['state'] == 'done',C.job_status(jid,'en')
    jd,raw = results.load(cid)
    elapsed = time.perf_counter()-started
    if tid in NEW and changes is None:
        print(f'PREVIEW {tid}: {elapsed:.2f} s',flush=True)
        assert elapsed < 120, f'{tid} preview took {elapsed:.2f} s'
    _solved[key] = cid,jd,raw
    return cid,jd,raw


@pytest.fixture(scope='module',params=[pytest.param(tid,marks=pytest.mark.slow) if tid in ('press-fit','large-cantilever','plastic-beam-collapse') else tid for tid in NEW])
def benchmark(request):
    return request.param,solve_template(request.param)


def test_templates_solve_and_verify(benchmark):
    tid,(cid,jd,raw) = benchmark
    assert raw['reference']['applicable'],raw
    assert raw['reference']['pass'],raw['reference']
    from novastudio.run_worker import primary_quantity
    quantity,value,unit = primary_quantity(store.load(cid),raw)
    assert np.isfinite(value) and unit
    if tid in ('plastic-bar','rubber-tension'):
        assert quantity == 'axial_stress'  # imposed displacement is not a mesh-study response
    assert raw['converged'] or tid == 'plastic-beam-collapse',raw
    for lang in ('en','ja','zh'):
        listed = {v['id']:v for v in C.list_templates(lang)['templates']}
        assert set(NEW)<=set(listed)
        assert not listed[tid]['title'].startswith('template.')
        assert not C.get_results(cid,lang=lang)['verification']['label'].startswith('verify.')
    if tid == 'plastic-beam-collapse':
        assert raw['error']['key'] == 'err.nonlinear_diverged'
        assert raw['limit_reached']
        assert any(w['code'] == 'limit_reached' for w in C.get_results(cid,lang='en')['warnings'])
        assert not C.verify_case(cid)['gates']['converged']
    else:
        assert C.verify_case(cid)['gates']['verified']


def assembly():
    """An imported two-body conformal patch, independent of the new Gmsh template branch."""
    m = generate([.02,.02,.04],[2,2,4])
    m['tet_body'] = np.where(m['nodes'][m['tets'][:,:4],2].mean(1)<.02,1,2)
    tri = {}
    for tet in m['tets']:
        for a,b,c in ((0,1,2),(0,1,3),(0,2,3),(1,2,3)):
            row = tet[[a,b,c]]
            if np.all(np.abs(m['nodes'][row,2]-.02)<1e-12):
                edge = {tuple(sorted((int(tet[i]),int(tet[j])))):int(tet[4+k]) for k,(i,j) in enumerate(fem.EDGES)}
                tri[tuple(sorted(row))] = list(row)+[edge[tuple(sorted((row[i],row[j])))] for i,j in ((0,1),(1,2),(2,0))]
    m['face_interface'] = np.array(list(tri.values()),int)
    m['face_bottom'] = m.pop('face_z0'); m['face_top'] = m.pop('face_z1')
    # The lower half of x1 has no applied shear.
    low = m['nodes'][m['face_x1'][:,:3],2].mean(1)<.02
    m['face_lower_x1'] = m['face_x1'][low]; m['face_x1'] = m['face_x1'][~low]
    c = templates.new_case('stacked-blocks','c_patch')
    c['geometry']['kind'] = 'import'
    return c,m


def patch_solve(c,m,al_factor=1.,large=False,steps=1):
    mesh,pairs = split_mesh(c,m)
    fixed,tractions = structural_loads(c,mesh)
    from novastudio.templates import element_groups
    return nl.solve(mesh['nodes'],mesh['tets'],element_groups(c,mesh['tet_body']),fixed,tractions,
                    symmetry_rollers(c,mesh),contact_pairs=pairs,steps=steps,large=large,al_factor=al_factor)


def test_01_duplication_and_bonded_regression():
    c,m = assembly()
    bonded = json.loads(json.dumps(c)); bonded.pop('contacts')
    unchanged,pairs = split_mesh(bonded,m)
    assert unchanged is m and not pairs
    explicit = json.loads(json.dumps(c)); explicit['contacts']['interface']['type'] = 'bonded'
    assert split_mesh(explicit,m)[0] is m
    fixed,tractions = structural_loads(c,m)
    before = fem.solve(m['nodes'],m['tets'],205e9,.3,fixed,tractions,rollers=symmetry_rollers(c,m))
    for case in (bonded,explicit):
        old,_ = split_mesh(case,m)
        now = fem.solve(old['nodes'],old['tets'],205e9,.3,fixed,tractions,rollers=symmetry_rollers(c,m))
        np.testing.assert_allclose(now['u'],before['u'],rtol=1e-10,atol=1e-20)
    split,pairs = split_mesh(c,m)
    interface = np.unique(m['face_interface'])
    assert len(split['nodes']) == len(m['nodes'])+len(interface)
    assert all(np.all(v['area']>0) for v in pairs)
    assert pairs[0]['area'].sum() == pytest.approx(.02**2,abs=1e-10)
    np.testing.assert_allclose(split['nodes'][pairs[0]['slave']],split['nodes'][pairs[0]['master']],atol=0)
    assert not set(split['tets'][split['tet_body'] == 1].ravel()) & set(pairs[0]['slave'])
    assert set(pairs[0]['slave']) <= set(split['tets'][split['tet_body'] == 2].ravel())
    np.testing.assert_allclose(pairs[0]['normal'],np.tile([0,0,1],(len(interface),1)),atol=1e-14)


def test_imported_shared_interface(tmp_path):
    import gmsh
    path = tmp_path/'touching.step'
    gmsh.initialize()
    previous_unit = gmsh.option.getString('Geometry.OCCTargetUnit')
    try:
        gmsh.option.setNumber('General.Terminal',0)
        gmsh.option.setString('Geometry.OCCTargetUnit','MM')
        gmsh.model.occ.addBox(0,0,0,20,20,20)
        gmsh.model.occ.addBox(0,0,20,20,20,20)
        gmsh.model.occ.synchronize(); gmsh.write(str(path))
    finally:
        gmsh.option.setString('Geometry.OCCTargetUnit',previous_unit)
        gmsh.finalize()
    p = C.import_geometry('structural',path.name,path=str(path),lang='en')
    cid = p['case']['case_id']; c = p['case']
    face = p['ui']['interfaces'][0]['key']
    assert p['ui']['interfaces'][0]['contact']['type'] == 'bonded'
    geometry.generate_mesh(c)
    m = dict(np.load(geometry.mesh_dir(c)/'mesh.npz')); key = geometry.mesh_key(c)
    c = C.update_case(cid,c['revision'],{f'contacts.{face}.type':'frictionless'},lang='en')['case']
    assert geometry.mesh_key(c) == key and not geometry.mesh_state(c)['stale']
    split,pairs = split_mesh(c,m)
    assert len(split['nodes']) == len(m['nodes'])+len(np.unique(m['face_'+face]))
    assert pairs[0]['area'].sum() == pytest.approx(.0004,abs=1e-10)


def test_02_contact_scaling_and_complementarity():
    c,m = assembly()
    base = patch_solve(c,m)
    assert base['converged'] and base['complementarity']<1e-6
    assert base['interfaces']['interface']['normal_force_n'] == pytest.approx(4000,rel=.005)
    for factor in (.1,10):
        r = patch_solve(c,m,al_factor=factor)
        np.testing.assert_allclose(r['u'],base['u'],atol=1e-12,rtol=.001)
        assert r['complementarity']<1e-6
    # An interference, unlike a prescribed pressure, exercises the contact constraint's right hand side.
    c['contacts']['interface']['offset'] = {'value':.02,'unit':'mm'}
    c['boundaries']['top'] = {'role':'constraint','components':'z'}
    base = patch_solve(c,m)
    for factor in (.1,10):
        assert patch_solve(c,m,al_factor=factor)['interfaces']['interface']['normal_force_n'] == pytest.approx(base['interfaces']['interface']['normal_force_n'],rel=.001)
    cid,_,press = solve_template('press-fit')
    c = store.load(cid); m = dict(np.load(geometry.mesh_dir(c)/'mesh.npz'))
    for factor in (.1,10):
        r = patch_solve(c,m,al_factor=factor)
        assert r['interfaces']['interface']['pressure_pa'] == pytest.approx(press['metrics']['contact_pressure_pa'],rel=.001)
        assert r['complementarity']<1e-6


def test_03_opening_is_a_mechanism_and_bilateral_holds():
    c,m = assembly(); c['boundaries']['top']['pressure'] = {'value':-10,'unit':'MPa'}
    with pytest.raises(StudioError,match='err.contact_unstable') as error:
        patch_solve(c,m)
    assert error.value.kw['body'] == 'b2'
    c['contacts']['interface']['type'] = 'no-separation'
    assert patch_solve(c,m)['converged']


def test_contact_iterative_path(monkeypatch):
    c,m = assembly()
    direct = patch_solve(c,m)
    monkeypatch.setattr(fem,'DIRECT_LIMIT',0)
    iterative = patch_solve(c,m)
    assert iterative['converged'] and iterative['complementarity']<1e-6
    np.testing.assert_allclose(iterative['u'],direct['u'],atol=1e-11,rtol=1e-5)


def test_05_large_deformation_is_active_and_newton_is_quadratic():
    cid,jd,r = solve_template('large-cantilever')
    linear = solve_template('large-cantilever',{'physics.analysis':'static'})[2]
    assert abs(linear['metrics']['max_disp_m']/r['metrics']['max_disp_m']-1)>.05
    hist = r['converged_detail']['residual_history'][-1]
    # The final displacement-polish iteration is at the floating-point residual floor.
    ratios = [b/a for a,b in zip(hist,hist[1:]) if a>1e-7]
    assert len(ratios)>=2 and ratios[-1]<ratios[-2]*.3,hist
    first = C.field(cid,'disp',step=1); final = C.field(cid,'disp',step=len(r['curve']))
    assert first['auto_deform_scale'] == final['auto_deform_scale'] == 1.
    assert max(first['scalars'])<max(final['scalars'])


def test_06_plastic_unload_and_divergence_retention():
    _,jd,r = solve_template('plastic-bar'); data = np.load(jd/'results.npz')
    peak = int(np.argmax([v['load_fraction'] for v in r['curve']]))
    stress = data['step_s'][peak,:,0].mean(); expected = 250e6+2.05e9*(.01-250e6/205e9)
    assert stress == pytest.approx(expected,rel=.01)
    zero = min(range(peak+1,len(r['curve'])),key=lambda i:abs(data['step_s'][i,:,0].mean()))
    strain = data['step_u'][zero,np.unique(np.load(jd/'mesh.npz')['face_x1']),0].mean()/.1
    assert strain == pytest.approx(.01-stress/205e9,rel=.01)
    assert abs(data['step_s'][zero,:,0].mean())<1e-5*250e6
    cid,jd,collapse = solve_template('plastic-beam-collapse')
    limit = 250e6*.01*.02**2/(4*.2)
    assert .97*limit <= collapse['metrics']['limit_load_n'] <= 1.03*limit
    assert collapse['error']['key'] == 'err.nonlinear_diverged'
    assert not C.get_results(cid)['gates']['converged']
    assert len(np.load(jd/'results.npz')['step_u']) == len(collapse['curve'])>1
    # Perfect plasticity: no nodal stress may sit outside the yield surface (extrapolation gave 282 MPa).
    assert collapse['metrics']['max_vm_pa'] <= 250e6*(1+1e-9)


def test_09_mcp_round_trip_undo_validation_and_localization():
    from novastudio import mcp_server
    p = C.create_case('press-fit',lang='en'); cid = p['case']['case_id']
    changes = {'contacts.interface.type':'frictional','contacts.interface.mu':.4,'contacts.interface.offset':'-0.01 mm',
               'physics.analysis':'nonlinear','physics.nonlinear':{'large_deformation':True,'steps':'auto','max_iterations':25}}
    result = asyncio.run(mcp_server.update_case(cid,1,changes,language='en'))
    assert not result.is_error
    case = C.describe_case(cid,'full','en')['case']
    assert case['contacts']['interface']['mu'] == .4 and case['physics']['nonlinear']['steps'] == 'auto'
    assert C.describe_case(cid,lang='en')['interfaces'][0]['contact']['type'] == 'frictional'
    assert not asyncio.run(mcp_server.undo_change(cid,language='en')).is_error
    assert store.load(cid)['contacts']['interface']['type'] == 'frictionless'
    for changes in ({'contacts.interface.mu':-1},{'physics.nonlinear.steps':0},{'materials.solid.model':'wrong'},
                    {'contacts.interface.offset':'3 MPa'},{'physics.nonlinear.max_iterations':float('nan')}):
        with pytest.raises(StudioError): store.apply_changes(store.load(cid),changes)
    for root in (Path(templates.__file__).parent/'i18n',Path(__file__).resolve().parents[2]/'frontend/src/i18n'):
        sets = [set(json.loads((root/(lang+'.json')).read_text(encoding='utf-8'))) for lang in ('en','ja','zh')]
        assert sets[0] == sets[1] == sets[2]
    assert len(asyncio.run(mcp_server.mcp.list_tools())) == 29


def test_10_follower_pressure_tangent():
    from novastudio.structural import follower_pressure
    c = templates.new_case('cantilever','c_test'); c['boundaries']['x1'] = {'role':'pressure','pressure':{'value':2,'unit':'MPa'}}
    m = generate([.1,.02,.02],[2,1,1]); load = follower_pressure(c,m)
    u = np.random.default_rng(2).normal(size=(len(m['nodes']),3))*.0001
    v = np.random.default_rng(3).normal(size=u.shape)
    f,K = load(u)
    diff = (load(u+1e-8*v)[0]-load(u-1e-8*v)[0])/2e-8
    np.testing.assert_allclose(diff,K@v.ravel(),rtol=1e-7,atol=1e-3)


def test_04_friction_stick_and_slip():
    _,_,stick = solve_template('friction-block')
    assert abs(stick['interfaces']['interface']['force_n'][0]) == pytest.approx(400,rel=.01)
    assert stick['interfaces']['interface']['status_counts']['open'] == 0
    assert stick['interfaces']['interface']['status_counts']['slip'] == 0
    _,_,slip = solve_template('friction-block',{'boundaries.x1.force':'1600 N'})
    assert abs(slip['interfaces']['interface']['force_n'][0]) == pytest.approx(800,rel=.01)
    assert slip['interfaces']['interface']['status_counts']['open'] == 0
    assert slip['interfaces']['interface']['status_counts']['stick'] == 0
    assert slip['interfaces']['interface']['status_counts']['slip']>0


def test_08_thermal_shrink_fit_and_large_contact():
    _,_,base = solve_template('press-fit')
    delta = .00002; alpha = 12e-6; radius = .02
    # Cooling the ring contracts the bore. Heating it has the opposite sign (tested separately below).
    cid,jd,cooled = solve_template('press-fit',{'contacts.interface.offset':'0 mm','physics.thermal_load.mode':'uniform',
        'physics.thermal_load.temperature':'20 degC','physics.thermal_load.body_temperatures':{'b2':{'value':20-delta/(alpha*radius),'unit':'degC'}}})
    assert cooled['interfaces']['interface']['pressure_pa'] == pytest.approx(base['interfaces']['interface']['pressure_pa'],rel=.03)
    _,_,heated = solve_template('press-fit',{'contacts.interface.offset':'0 mm','physics.thermal_load.mode':'uniform',
        'physics.thermal_load.temperature':'20 degC','physics.thermal_load.body_temperatures':{'b2':{'value':20+delta/(alpha*radius),'unit':'degC'}}})
    assert abs(heated['interfaces']['interface']['pressure_pa'])<base['interfaces']['interface']['pressure_pa']*1e-6
    assert heated['interfaces']['interface']['status_counts']['stick'] == 0
    # Fixed contact pairs/normals cannot represent finite sliding or rotation.
    p = C.create_case('press-fit',{'physics.analysis':'nonlinear','physics.nonlinear':{'large_deformation':True,'steps':2,'max_iterations':25}})
    assert any(i['code'] == 'contact_large_deformation' for i in p['checks'])
    with pytest.raises(StudioError,match='err.blocked'):
        C.run_simulation(p['case']['case_id'],lang='en')


def test_11_results_export_and_steps():
    import xml.etree.ElementTree as ET
    import csv
    cid,jd,raw = solve_template('rubber-tension')
    assert 'peeq' in {q['id'] for q in C.get_results(cid)['quantities']}
    for step in (1,len(raw['curve'])):
        assert C.render_view(cid,'peeq',step=step)[0].startswith(b'\x89PNG')
    path = Path(C.export_results(cid,'vtu',lang='en')['path'])
    assert path.suffix == '.pvd'
    entries = ET.parse(path).findall('.//DataSet')
    assert len(entries) == len(raw['curve'])
    for e in entries:
        root = ET.parse(path.parent/e.attrib['file'])
        assert {'u','s','vm','peeq'} <= {v.attrib.get('Name') for v in root.findall('.//PointData/DataArray')}
    with Path(C.export_results(cid,'csv')['path']).open(newline='') as fh:
        rows = list(csv.reader(fh))
    assert rows[0][0:2] == ['step','load_fraction'] and len(rows) == len(raw['curve'])+1
    report = Path(C.export_results(cid,'report',lang='en')['path']).read_text(encoding='utf-8')
    assert 'Load–displacement curve' in report and 'neo-hookean' in report
    cid,jd,raw = solve_template('press-fit')
    assert C.field(cid,'p_contact')['range'][1]>0
    assert C.get_results(cid)['interfaces']['interface']['status_counts']
    report = Path(C.export_results(cid,'report',lang='en')['path']).read_text(encoding='utf-8')
    assert 'Contacts' in report


def test_12_deck_and_material_readiness():
    from novastudio.external import compile_calculix
    c,m = assembly(); text = compile_calculix(c,m,temperature=None)
    assert '*CONTACT PAIR' in text and '*SURFACE BEHAVIOR' in text and '*CLEARANCE' in text
    c['contacts']['interface']['type'] = 'frictional'
    assert '*FRICTION' in compile_calculix(c,m,temperature=None)
    c = templates.new_case('plastic-beam-collapse','c_test')
    m = generate([.2,.01,.02],[2,1,1])
    assert '*PLASTIC' in compile_calculix(c,m,temperature=None)
    c = templates.new_case('large-cantilever','c_test')
    assert '*STEP, NLGEOM' in compile_calculix(c,m,temperature=None)
    c = templates.new_case('rubber-tension','c_test')
    with pytest.raises(StudioError,match='err.final_unsupported'):
        compile_calculix(c,m,temperature=None)
    p = C.create_case('rubber-tension',{'physics.nonlinear.large_deformation':False})
    assert any(i['code'] == 'neo_large' and i['level'] == 'error' for i in p['checks'])
    p = C.create_case('plastic-bar',{'physics.nonlinear.large_deformation':True})
    assert any(i['code'] == 'plastic_large' and i['level'] == 'error' for i in p['checks'])


@pytest.mark.parametrize('tid',['press-fit','large-cantilever'])
def test_calculix_comparison_when_installed(tid):
    from novastudio.config import find_calculix
    if not find_calculix():
        pytest.skip('CalculiX not installed')
    _,_,builtin = solve_template(tid)
    _,_,ccx = solve_template(tid,{'run.mode':'final'})
    metric = 'contact_pressure_pa' if tid == 'press-fit' else 'tip_disp_m'
    assert ccx['metrics'][metric] == pytest.approx(builtin['metrics'][metric],rel=.03)


def test_j2_consistent_tangent_and_unloading():
    E,nu,sy,H = 205e9,.3,250e6,2.05e9
    strain = np.array([[.01,-.004,-.004,.002,.001,0.]])
    zero = np.zeros_like(strain); eq = np.zeros(1)
    stress,D,ep,q = nl.radial_return(strain,E,nu,sy,H,zero,eq)
    for c in range(6):
        h = np.zeros_like(strain); h[:,c] = 1e-7
        diff = (nl.radial_return(strain+h,E,nu,sy,H,zero,eq)[0]-nl.radial_return(strain-h,E,nu,sy,H,zero,eq)[0])/2e-7
        np.testing.assert_allclose(diff[0],D[0,:,c],atol=100,rtol=1e-6)
    assert q[0]>0
    np.testing.assert_allclose(nl.radial_return(ep,E,nu,sy,H,ep,q)[0],0,atol=1e-5)


@pytest.mark.parametrize('model,large',[('linear',False),('linear',True),('neo-hookean',True),('elastoplastic',False)])
def test_element_consistent_tangent(model,large):
    mesh = generate([.01,.01,.05],[1,1,1])
    props = {'E':5e6,'nu':.45,'model':model,'sy':1e4,'H':5e4}
    mech = nl.Mechanics(mesh['nodes'],mesh['tets'],[(np.arange(6),props)],large)
    u = np.random.default_rng(13).normal(size=3*len(mesh['nodes']))*1e-4
    K,f,*_ = mech.assemble(u)
    v = np.random.default_rng(14).normal(size=len(u))
    diff = (mech.assemble(u+1e-8*v)[1]-mech.assemble(u-1e-8*v)[1])/2e-8
    np.testing.assert_allclose(diff,K@v,rtol=2e-5,atol=.05)


def test_linear_displacement_patch():
    mesh = generate([.1,.01,.01],[3,1,1])
    r = nl.solve(mesh['nodes'],mesh['tets'],[(np.arange(len(mesh['tets'])),{'E':205e9,'nu':.3})],[],[],
        [(mesh['face_y0'],1),(mesh['face_z0'],2),(mesh['face_x0'],0)],[(mesh['face_x1'],0,.001)],steps=1)
    assert r['converged']
    np.testing.assert_allclose(r['s'][:,0],205e9*.01,rtol=1e-9)


def test_neo_homogeneous_patch():
    from novastudio.structural import rubber_uniaxial
    mesh = generate([.01,.01,.05],[1,1,2])
    p = {'E':26e6,'nu':.45,'model':'neo-hookean'}
    r = nl.solve(mesh['nodes'],mesh['tets'],[(np.arange(len(mesh['tets'])),p)],[],[],
        [(mesh['face_x0'],0),(mesh['face_y0'],1),(mesh['face_z0'],2)],[(mesh['face_z1'],2,.05)],steps=5,large=True)
    assert r['converged'],r.get('error')
    expected = rubber_uniaxial(p['E'],p['nu'],2.)
    np.testing.assert_allclose(r['s'][:,2],expected['cauchy_pa'],rtol=.02)


def test_fix01_contact_large_deformation_refused(monkeypatch):
    from novastudio import checks
    from novastudio.external import compile_calculix
    c,m = assembly()
    monkeypatch.setattr(geometry,'mesh_state',lambda _: {'exists':False,'stale':False})
    c['physics'].update(analysis='nonlinear',nonlinear={'large_deformation':True})
    for lang in ('en','ja','zh'):
        item = next(i for i in checks.run(c,lang) if i['code'] == 'contact_large_deformation')
        assert item['level'] == 'error' and not item['message'].startswith('check.')
    with pytest.raises(StudioError,match='err.contact_large_deformation'):
        patch_solve(c,m,large=True)
    with pytest.raises(StudioError,match='err.contact_large_deformation'):
        compile_calculix(c,m)


def test_fix02_modal_displacement_and_springs(tmp_path,monkeypatch):
    from novastudio.run_worker import run_modal
    from novastudio.external import compile_calculix
    from novastudio import checks
    monkeypatch.setattr(geometry,'mesh_state',lambda _: {'exists':False,'stale':False})
    c = templates.new_case('cantilever-modal','c_modal_fix')
    m = generate([.1,.01,.01],[3,1,1])
    baseline = run_modal(c,tmp_path,lambda *_:None,m)
    c['boundaries']['x0'] = {'role':'displacement',**{k:{'value':0,'unit':'mm'} for k in ('ux','uy','uz')}}
    constrained = run_modal(c,tmp_path,lambda *_:None,m)
    assert constrained['modes'][0]['frequency_hz'] == pytest.approx(baseline['modes'][0]['frequency_hz'],rel=1e-8)
    assert not constrained['free_free']
    deck = compile_calculix(c,m)
    before = deck.split('*STEP')[0]
    for node in np.unique(m['face_x0']):
        for axis in range(1,4):
            assert f'{node+1}, {axis}, {axis}, 0.000000000000e+00' in before
    c['boundaries']['x1'] = {'role':'spring','components':'xyz','stiffness':{'value':1e7,'unit':'N/m'}}
    stiff = run_modal(c,tmp_path,lambda *_:None,m)
    assert stiff['modes'][0]['frequency_hz'] > 2*constrained['modes'][0]['frequency_hz']
    c['boundaries']['x1'] = {'role':'displacement','ux':{'value':1,'unit':'mm'},'uy':None,'uz':None}
    assert any(i['code'] == 'modal_displacement_ignored' for i in checks.run(c,'en'))
    ignored = run_modal(c,tmp_path,lambda *_:None,m)
    assert ignored['modes'][0]['frequency_hz'] == pytest.approx(constrained['modes'][0]['frequency_hz'],rel=1e-8)
    np.testing.assert_allclose(np.load(tmp_path/'results.npz')['mode_shapes'][:,np.unique(m['face_x0'])],0,atol=1e-10)


def test_fix04_body_temperature_order_and_element_strain(tmp_path,monkeypatch):
    from novastudio.structural import temperatures
    c,m = assembly()
    c['physics']['thermal_load'] = {'mode':'uniform','body_temperatures':{
        'b1':{'value':20,'unit':'degC'},'b2':{'value':120,'unit':'degC'}}}
    a = temperatures(c,m,lambda *_:None)
    c['physics']['thermal_load']['body_temperatures'] = dict(reversed(list(c['physics']['thermal_load']['body_temperatures'].items())))
    b = temperatures(c,m,lambda *_:None)
    np.testing.assert_array_equal(a,b)
    assert a.shape == (len(m['tets']),4)
    np.testing.assert_allclose(a[m['tet_body'] == 1],293.15)
    np.testing.assert_allclose(a[m['tet_body'] == 2],393.15)
    tets = fem.canonical_tets(m['nodes'],m['tets'])
    K,force,*_ = fem.structural_system(m['nodes'],tets,205e9,.3,12e-6,a)
    groups = templates.element_groups(c,m['tet_body'])
    mech = nl.Mechanics(m['nodes'],m['tets'],groups,False,12e-6,b)
    np.testing.assert_allclose(mech.expansion[m['tet_body'] == 1],0,atol=1e-15)
    np.testing.assert_allclose(mech.expansion[m['tet_body'] == 2],.0012)
    np.testing.assert_allclose(mech.assemble(np.zeros(K.shape[0]))[1],-force,atol=1e-8)
    from novastudio import run_worker
    c['contacts'] = {}
    monkeypatch.setattr(run_worker,'_mesh_for_run',lambda *_:m)
    run_worker.run_structural_builtin(c,tmp_path,lambda *_:None)
    assert np.load(tmp_path/'results.npz')['T'].shape == (len(m['nodes']),)
    from novastudio.external import compile_calculix
    with pytest.raises(StudioError,match='err.final_body_temperatures'):
        compile_calculix(c,m)


@pytest.mark.parametrize('preset',['steel','rubber','tpu'])
def test_fix05_preset_replaces_constitutive_fields(preset):
    c = templates.new_case('plastic-bar','c_preset_fix')
    changed,_ = store.apply_changes(c,{'materials.solid.preset':preset})
    props = templates.solid_props(changed)
    assert props['model'] == templates.MATERIALS_SOLID[preset].get('model','linear')
    assert props['H'] == props['E']/100
    if 'sy' not in templates.MATERIALS_SOLID[preset]:
        assert 'sy' not in changed['materials']['solid']
    custom,_ = store.apply_changes(c,{'materials.solid.preset':'custom'})
    assert custom['materials']['solid']['model'] == 'elastoplastic'


def test_fix06_collapse_reference_missing_history():
    from novastudio.structural import reference
    c = templates.new_case('plastic-beam-collapse','c_history_fix')
    m = generate([.2,.01,.02],[1,1,1])
    r = {'u':np.zeros_like(m['nodes']),'s':np.zeros((len(m['nodes']),6))}
    ref = reference(c,m,r,{})
    assert not ref['applicable'] and ref['why_key'] == 'verify.history_missing'
    r['curve'] = [{'load_fraction':1/1.1}]
    metrics = {}
    assert reference(c,m,r,metrics)['pass']
    assert metrics['limit_load_n'] == pytest.approx(1250)


@pytest.mark.parametrize('history',[True,False])
def test_fix06_calculix_passes_parsed_history(tmp_path,monkeypatch,history):
    from novastudio import external,run_worker
    c = templates.new_case('plastic-beam-collapse','c_ccx_history')
    m = generate([.2,.01,.02],[1,1,1])
    frame = {'time':1/1.1,'DISP':np.zeros_like(m['nodes']),'STRESS':np.zeros((len(m['nodes']),6)),
             'PE':np.full((len(m['nodes']),1),.01)}
    monkeypatch.setattr(external,'find_calculix',lambda:'ccx')
    monkeypatch.setattr(run_worker,'_mesh_for_run',lambda *_:m)
    def process(*_):
        (tmp_path/'ccx/job.frd').touch()
        return 0
    monkeypatch.setattr(external,'_proc',process)
    monkeypatch.setattr(external,'parse_frd',lambda *args,**kw:([frame] if history else []) if kw.get('history') else frame)
    out = external.run_calculix(c,tmp_path,lambda *_:None)
    if history:
        assert out['reference']['pass']
        np.testing.assert_allclose(np.load(tmp_path/'results.npz')['step_peeq'],.01)
    else:
        assert out['reference']['why_key'] == 'verify.history_missing'


@pytest.mark.parametrize('path',[[101],[-101],[0]*51,[float('nan')],[float('inf')]])
def test_fix07_path_validation(path):
    p = C.create_case('large-cantilever',lang='en'); c = p['case']
    with pytest.raises(StudioError):
        C.update_case(c['case_id'],c['revision'],{'physics.nonlinear.path':path},lang='en')


def test_fix07_history_cap_and_memory_estimate(monkeypatch):
    monkeypatch.setattr(nl,'SNAPSHOT_CAP',6)
    estimates = []
    monkeypatch.setattr(fem,'check_memory',lambda n,k,steps:estimates.append(steps))
    m = generate([.1,.01,.01],[1,1,1])
    progress = []
    r = nl.solve(m['nodes'],m['tets'],[(np.arange(len(m['tets'])),{'E':205e9,'nu':.3})],[],[],
        [(m['face_y0'],1),(m['face_z0'],2),(m['face_x0'],0)],[(m['face_x1'],0,.001)],
        steps=1,path=[5,0,5,0],face_nodes=np.unique(m['face_x1']),progress=lambda k,f,a:progress.append((f,a)))
    assert 1 < estimates[0] <= 7
    assert len(r['steps']) == len(r['curve']) == len(r['residual_history']) <= 6
    assert r['curve'][-1]['load_fraction'] == 0
    np.testing.assert_allclose(r['steps'][-1]['u'],0,atol=1e-12)
    assert all(f == a['converged_fraction'] for f,a in progress)


def test_fix08_zero_path_is_validation_error():
    c,m = assembly()
    with pytest.raises(StudioError,match='err.nonlinear_empty_path'):
        nl.solve(m['nodes'],m['tets'],templates.element_groups(c,m['tet_body']),[],[],path=[0])


def test_fix09_divergence_detection():
    assert nl.diverging([1,2,3,4])
    assert nl.diverging([1,1e4])
    assert not nl.diverging([1,.2,.03,1e-7])


def test_fix10_progress_reports_converged_fraction_without_eta():
    from novastudio.commands import job_view
    j = {'job_id':'r_test','case_id':'c_test','state':'running','created_at':time.time()-10,
         'progress':.4,'message_key':'job.nonlinear','message_args':{'step':9,'steps':10,'iteration':2,'fraction':.5,'converged_fraction':.4}}
    view = job_view(j,'en')
    assert view['eta_s'] is None
    assert view['progress'] == pytest.approx(.4)
    # The cut-back messages near a limit load are nonlinear progress too: no ETA, and the text names the increment.
    view = job_view({**j,'message_key':'job.nonlinear_limit','message_args':{'fraction':.925,'increment':.0125,'converged_fraction':.925}},'en')
    assert view['eta_s'] is None and '0.0125' in view['message']


def test_fix12_flat_gauss_average_stays_inside_bounds():
    m = generate((.1,.02,.01),(4,2,1)); nodes,tets = m['nodes'],m['tets']
    rng = np.random.default_rng(1)
    values = rng.uniform(-1,1,(len(tets),4))
    flat = np.ones(len(tets),bool)
    out = fem.gauss_to_nodes(tets,values,len(nodes),flat=flat)
    assert out.max() <= values.max()+1e-12 and out.min() >= values.min()-1e-12
    assert fem.gauss_to_nodes(tets,values,len(nodes)).max() > values.max()   # plain extrapolation overshoots


def test_fix11_self_equilibrated_cards(monkeypatch):
    cid,jd,raw = solve_template('press-fit')
    cards = {c['key']:c for c in C.get_results(cid,lang='en')['cards']}
    assert 'reaction' not in cards
    assert cards['contact_force']['value'] == pytest.approx(raw['interfaces']['interface']['normal_force_n'],rel=5e-4)
    quiet = {**raw,'interfaces':{},'metrics':{**raw['metrics'],'applied_n':4.243e-10,
        'reaction_n':4.243e-10,'force_scale_n':1e4}}
    monkeypatch.setattr(results,'load',lambda *_:(jd,quiet))
    assert 'reaction' not in {c['key'] for c in C.get_results(cid,lang='en')['cards']}
