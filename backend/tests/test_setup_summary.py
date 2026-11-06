"""Setup mistakes a check cannot see (validation/mistakes.py, 0.7.6): a temperature typed in kelvin is warned; a load
on the wrong face or pointing the wrong way is stated in words so the person can compare it with what they meant."""
from __future__ import annotations

import pytest

from novastudio import commands as C, store
from novastudio.i18n import LANGS


@pytest.fixture(autouse=True)
def private_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv('NOVASTUDIO_WORKSPACE', str(tmp_path / 'cases_root'))


def edit(cid, changes):
    return C.update_case(cid, store.load(cid)['revision'], changes, 'en')


def codes(cid):
    return {i['code'] for i in C.validate_case(cid, 'en')['items']}


def test_kelvin_typed_for_celsius_is_warned():
    cid = C.create_case('thermal-block')['case']['case_id']
    assert 'cold_temperature' not in codes(cid)
    edit(cid, {'boundaries.x0.temperature': {'value': 100, 'unit': 'K'}})
    item = next(i for i in C.validate_case(cid, 'en')['items'] if i['code'] == 'cold_temperature')
    assert item['faces'] == ['x0'] and '-173.1' in item['message'] and '"100 degC"' in item['fix']
    edit(cid, {'boundaries.x0.temperature': {'value': 373.15, 'unit': 'K'}})     # 100 °C written in kelvin is fine
    assert 'cold_temperature' not in codes(cid)
    edit(cid, {'boundaries.x0.temperature': '-40 degC'})                         # cold, but not cryogenic
    assert 'cold_temperature' not in codes(cid)


def test_setup_states_face_direction_and_lever():
    cid = C.create_case('cantilever')['case']['case_id']
    s = C.validate_case(cid, 'en')['setup']
    assert s[0].startswith('x1 ') and 'toward -z' in s[0] and 'along it' in s[0] and '2.5 MPa' in s[0]
    assert '200 mm' in s[1] and '200 N·m' in s[1]
    assert any(x.startswith('Held: x0') for x in s) and any('E 205 GPa' in x for x in s)
    edit(cid, {'boundaries.x1.direction': '+z'})                     # wrong way: the summary says so
    assert 'toward +z' in C.validate_case(cid, 'en')['setup'][0]
    edit(cid, {'boundaries.x1.role': 'free', 'boundaries.z1.role': 'load', 'boundaries.z1.force': '1000 N',
               'boundaries.z1.direction': '-z'})                     # wrong face: the top, pushed on, 100 mm arm
    s = C.validate_case(cid, 'en')['setup']
    assert s[0].startswith('z1 ') and 'pushes on it' in s[0] and '100 mm' in s[1]
    for lang in LANGS:
        assert all('{' not in x for x in C.validate_case(cid, lang)['setup'])


def test_setup_for_thermal_in_celsius():
    cid = C.create_case('thermal-block')['case']['case_id']
    s = C.validate_case(cid, 'en')['setup']
    assert 'x0' in s[0] and '100 °C' in s[0] and any('conductivity' in x for x in s)
