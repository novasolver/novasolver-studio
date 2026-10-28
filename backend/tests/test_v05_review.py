"""Regressions for the second-opinion review of v0.5."""
import copy
import json

import numpy as np
import pytest

from novastudio import commands as C, external, fem_tet10 as fem, probe, results, store, structural, templates
from novastudio import run_worker as worker


def reference(case):
    nodes = np.array([[0, 0, 0], [.05, .01, .1], [.1, 0, .2]])
    mesh = {'nodes': nodes, **{'face_'+f: np.array([[0, 1, 2]]) for f in case['boundaries']}}
    metrics = {'t_rise_k': 1., 'capacitance_f': 1., 'e_max_v_m': 1.}
    tid = case['template']
    if tid == 'cantilever':
        return worker.reference_cantilever(case, .001)
    if tid == 'plate-hole':
        from novastudio.units import to_si
        nodes[0, :2] = [to_si(case['geometry']['params'][k])/2 for k in ('length', 'width')]
        return worker.reference_plate_hole(case, nodes, np.ones(3), metrics)
    if tid == 'thermal-block':
        return worker.reference_thermal_block(case, {})
    if tid == 'fin':
        return worker.reference_fin(case, {})
    if tid in ('capacitor', 'coax', 'busbar'):
        return worker.reference_electric(case, metrics)
    if tid == 'cantilever-modal':
        return structural.modal_reference(case, [{'frequency_hz': 200.}])
    return structural.reference(case, mesh, {'u': np.zeros((3, 3)), 's': np.ones((3, 6)), 'vm': np.ones(3)}, metrics)


TEMPLATES = ('cantilever', 'plate-hole', 'thermal-block', 'fin', 'capacitor', 'coax', 'busbar',
             'cantilever-modal', 'thermal-bar-fixed', 'thermal-bar-free', 'hanging-bar', 'rotating-disk', 'shaft-torsion')


@pytest.mark.parametrize('tid', TEMPLATES)
@pytest.mark.parametrize('load', ('gravity', 'rotation', 'thermal'))
def test_reference_identifies_unmodeled_body_load(tid, load):
    if (tid.startswith('thermal-bar-') and load == 'thermal') or (tid == 'hanging-bar' and load == 'gravity') or (tid == 'rotating-disk' and load == 'rotation'):
        pytest.skip('this is the load modeled by the formula')
    c = templates.new_case(tid, 'c_test')
    c['physics'][load if load != 'thermal' else 'thermal_load'] = {'enabled': True} if load != 'thermal' else {'mode': 'uniform', 'temperature': {'value': 120, 'unit': 'degC'}}
    ref = reference(c)
    assert not ref['applicable'], ref
    assert load in ref.get('why', ''), ref


@pytest.mark.parametrize('role', ('moment', 'bearing', 'remote-force', 'pressure', 'future-load'))
def test_reference_identifies_unmodeled_face_role(role):
    c = templates.new_case('cantilever', 'c_test')
    c['boundaries']['y1'] = {'role': role}
    ref = reference(c)
    assert not ref['applicable'] and role in ref.get('why', ''), ref


def quadratic_tet():
    corners = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], float)
    return np.vstack([corners, (corners[fem.EDGES[:, 0]]+corners[fem.EDGES[:, 1]])/2]), np.arange(10)[None]


@pytest.mark.parametrize('quantity', ('uz', 'mode'))
def test_section_uses_original_quadratic_interpolant(tmp_path, quantity):
    from novastudio.sections import section_field
    nodes, tets = quadratic_tet()
    u = np.zeros_like(nodes)
    u[:, 2] = nodes[:, 0]**2
    np.savez(tmp_path/'mesh.npz', nodes=nodes, tets=tets)
    np.savez(tmp_path/'results.npz', u=u, vm=np.zeros(10), mode_shapes=u[None])
    scale = 1000 if quantity == 'uz' else 1
    triangles = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]])
    p, _, v, displacement = section_field(tmp_path, 'structural' if quantity == 'uz' else 'modal', quantity, 1,
        nodes, triangles, u[:, 2]*scale, u, {'normal': [1, 0, 0], 'position': .25})
    cut = np.abs(p[:, 0]-.25) < 1e-8
    assert cut.any()
    np.testing.assert_allclose(v[cut]/scale, .0625, atol=1e-9, rtol=0)
    np.testing.assert_allclose(displacement[cut, 2], .0625, atol=1e-9, rtol=0)


@pytest.mark.parametrize('role', ('moment', 'bearing', 'remote-force'))
def test_role_change_revalidates_retained_direction(role):
    c = templates.new_case('cantilever', 'c_test')
    c, _ = store.apply_changes(c, {'boundaries.x1.direction': 'normal'})
    changed, _ = store.apply_changes(c, {'boundaries.x1.role': role})
    assert changed['boundaries']['x1']['direction'] == templates.ROLE_FIELDS[role]['direction']
    assert np.isfinite(structural.direction(changed['boundaries']['x1']['direction'])).all()
    if role == 'moment':
        nodes, tets = quadratic_tet()
        mesh = {'nodes': nodes, 'tets': tets, 'face_x1': np.array([[1, 2, 3, 5, 9, 8]])}
        _, tractions = worker.structural_loads(changed, mesh)
        assert np.isfinite(tractions[0][1]).all()


def test_disconnected_modal_skips_twelve_rigid_modes():
    from test_memory_2026_10_28 import block_mesh
    nodes, tets, x0, _, _ = block_mesh(n=2, L=(.04, .02, .02))
    single = fem.solve_modal(nodes, tets, 205e9, .3, 7850., modes=6)
    pair_nodes = np.vstack([nodes, nodes+[.1, 0, 0]])
    pair_tets = np.vstack([tets, tets+len(nodes)])
    pair = fem.solve_modal(pair_nodes, pair_tets, 205e9, .3, 7850., modes=6)
    assert pair['converged'] and len(pair['modes']) == 6
    assert pair['modes'][0]['frequency_hz'] == pytest.approx(single['modes'][0]['frequency_hz'], rel=.01)
    # Also count each component's remaining rigid modes under partial and full constraints.
    assert fem.modal_constraints(pair_nodes, [], [], tets=pair_tets)[2] == 12
    assert fem.modal_constraints(pair_nodes, [x0], [], tets=pair_tets)[2] == 6
    assert fem.modal_constraints(pair_nodes, [], [(x0, 0)], tets=pair_tets)[2] == 9


@pytest.mark.parametrize('value', ('25 mm', 25, {'value': 25, 'unit': 'mm'}, [1, 2],
    {'value': [1, 2, float('nan')], 'unit': 'mm'}, [1, 2, 3, 4], None, {'value': [[1], 2, 3], 'unit': 'mm'}))
def test_remote_point_requires_three_finite_coordinates(value):
    c = templates.new_case('cantilever', 'c_test')
    before = copy.deepcopy(c)
    with pytest.raises(store.StudioError) as err:
        store.apply_changes(c, {'boundaries.x1.role': 'remote-force', 'boundaries.x1.point': value})
    assert err.value.key in ('err.path', 'err.range')
    assert c == before


@pytest.mark.parametrize('value', ([1, 2, 3], {'value': [1, 2, 3], 'unit': 'cm'}))
def test_remote_point_accepts_finite_vectors(value):
    c = templates.new_case('cantilever', 'c_test')
    changed, _ = store.apply_changes(c, {'boundaries.x1.role': 'remote-force', 'boundaries.x1.point': value})
    from novastudio.units import to_si
    expected = np.array([1, 2, 3])*(.01 if isinstance(value, dict) else .001)
    np.testing.assert_allclose(to_si(changed['boundaries']['x1']['point']), expected)


def test_probe_http_pins_requested_run(monkeypatch):
    from fastapi.testclient import TestClient
    from novastudio.api import app
    calls = []
    def fake_probe(case_id, **kwargs):
        calls.append((case_id, kwargs))
        return {'points': []}
    monkeypatch.setattr(C, 'probe_results', fake_probe)
    response = TestClient(app, base_url='http://127.0.0.1').post('/api/cases/c_test/probe',
        json={'points': [[250, 100, 100]], 'run_id': 'j_old', 'mode': 2})
    assert response.status_code == 200
    assert calls[0][0] == 'c_test' and calls[0][1]['run_id'] == 'j_old' and calls[0][1]['mode'] == 2


@pytest.mark.parametrize('thermal_mode', ('uniform', 'solve'))
def test_calculix_preserves_applied_temperature_contract(tmp_path, monkeypatch, thermal_mode):
    from test_memory_2026_10_28 import block_mesh
    monkeypatch.setenv('NOVASTUDIO_WORKSPACE', str(tmp_path/'cases_root'))
    c = store.create('thermal-bar-free')
    c, _ = store.apply_changes(c, {'physics.thermal_load.mode': thermal_mode,
        'boundaries.x0.thermal.role': 'temperature', 'boundaries.x0.thermal.temperature': '0 degC',
        'boundaries.x1.thermal.role': 'temperature', 'boundaries.x1.thermal.temperature': '100 degC'})
    store.save(c)
    nodes, tets, x0, x1, y0 = block_mesh(n=2, L=(.1, .01, .01))
    # The structural symmetry faces are not used by the fake solver; the thermal solver needs the end faces.
    mesh = {'nodes': nodes, 'tets': tets, 'face_x0': x0, 'face_x1': x1, 'face_y0': y0}
    c['boundaries']['z0']['role'] = 'free'
    c['boundaries']['x0']['role'] = 'fixed'
    jd = store.case_dir(c['case_id'])/'jobs'/'j_fake'
    jd.mkdir(parents=True)
    np.savez(jd/'mesh.npz', **mesh)
    monkeypatch.setattr(worker, '_mesh_for_run', lambda *_: mesh)
    monkeypatch.setattr(external, 'find_calculix', lambda: 'fake-ccx')
    def fake_proc(argv, wd, *_):
        (wd/'job.frd').write_text('', encoding='utf-8')
        return 0
    monkeypatch.setattr(external, '_proc', fake_proc)
    monkeypatch.setattr(external, 'parse_frd', lambda *_: {'DISP': np.zeros_like(nodes), 'STRESS': np.zeros((len(nodes), 6))})
    calls = []
    temperatures = structural.temperatures
    def applied_temperature(*args):
        calls.append(temperatures(*args))
        return calls[-1]
    monkeypatch.setattr(structural, 'temperatures', applied_temperature)
    raw = external.run_calculix(c, jd, lambda *_: None)
    assert len(calls) == 1
    raw.update(case_id=c['case_id'], revision=c['revision'], run_id=jd.name)
    (jd/'results.json').write_text(json.dumps(raw), encoding='utf-8')
    monkeypatch.setattr(results, 'load', lambda *_: (jd, raw))
    monkeypatch.setattr(probe, 'load', lambda *_: (jd, raw))
    expected = np.full(len(nodes), 393.15) if thermal_mode == 'uniform' else 273.15+100*nodes[:, 0]/.1
    deck = (jd/'ccx'/'job.inp').read_text(encoding='utf-8').split('*TEMPERATURE\n')[1].split('*NODE FILE')[0]
    np.testing.assert_allclose([float(line.split(',')[1]) for line in deck.splitlines()], expected, atol=1e-6, rtol=0)
    with np.load(jd/'results.npz') as data:
        np.testing.assert_allclose(data['T'], expected, atol=1e-6, rtol=0)
    assert raw['metrics']['t_min_k'] == pytest.approx(expected.min())
    assert raw['metrics']['t_max_k'] == pytest.approx(expected.max())
    assert C.field(c['case_id'], 'temp')['quantity'] == 'temp'
    sampled = probe.probe(c, points=[[50, 5, 5]])
    assert sampled['points'][0]['values']['temp'] == pytest.approx(120 if thermal_mode == 'uniform' else 50)
    from novastudio.exports import export
    exported = export(c, 'csv', 'en')
    assert 'T' in exported.read_text(encoding='utf-8').splitlines()[0].split(',')
