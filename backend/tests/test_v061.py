"""0.6.1: .nscase case archives and solved examples."""
from __future__ import annotations

import functools
import hashlib
import http.server
import io
import json
import os
import threading
import time
import zipfile
from pathlib import Path

import pytest

from novastudio import archive, commands as C, examples, jobs, store
from novastudio.store import StudioError


@pytest.fixture(scope='module', autouse=True)
def private_dirs(tmp_path_factory):
    old = {k: os.environ.get(k) for k in ('NOVASTUDIO_WORKSPACE', 'LOCALAPPDATA', 'NOVASTUDIO_EXAMPLES_URL')}
    os.environ['NOVASTUDIO_WORKSPACE'] = str(tmp_path_factory.mktemp('v061ws'))
    os.environ['LOCALAPPDATA'] = str(tmp_path_factory.mktemp('v061data'))
    yield
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@functools.lru_cache(maxsize=None)
def solved(tid='plastic-bar'):
    cid = C.create_case(tid, lang='en')['case']['case_id']
    j = jobs.wait(C.run_simulation(cid, wait_s=1, lang='en')['job']['job_id'], 900)
    assert j['state'] == 'done', j
    return cid


def comparable(cid):
    res = C.get_results(cid, lang='en')
    ver = C.verify_case(cid, lang='en')
    vm = C.field(cid, 'vm', lang='en')
    drop = lambda d: {k: v for k, v in d.items() if k not in ('case_id', 'run_id', 'job_id', 'revision_note')}
    return [(c['key'], c['value'], c['unit']) for c in res['cards']], drop(ver), json.dumps(drop(vm), sort_keys=True)


def test_round_trip_keeps_result_and_verification():
    cid = solved()
    path = Path(C.export_case(cid, lang='en')['path'])
    new = C.import_case(path=str(path), lang='en')['case']['case_id']
    assert new != cid
    a, b = comparable(cid), comparable(new)
    assert a[0] == b[0] and a[2] == b[2]
    assert a[1]['verification'] == b[1]['verification'] and not b[1]['stale']
    # the imported job has its own id, so job lookups across cases stay unambiguous
    assert {j['job_id'] for j in jobs.list_for_case(cid)}.isdisjoint(j['job_id'] for j in jobs.list_for_case(new))
    case = store.load(new)
    assert case['provenance']['imported_from']['case_id'] == cid
    C.update_case(new, case['revision'], {'materials.solid.E': {'value': 100, 'unit': 'GPa'}}, lang='en')
    assert C.verify_case(new, lang='en')['stale']


def test_export_is_deterministic_and_private():
    cid = solved()
    p1 = Path(C.export_case(cid, lang='en')['path']); h1 = hashlib.sha256(p1.read_bytes()).hexdigest()
    time.sleep(1.1)
    p2 = Path(C.export_case(cid, lang='en')['path']); h2 = hashlib.sha256(p2.read_bytes()).hexdigest()
    assert h1 == h2
    secrets = [os.environ['NOVASTUDIO_WORKSPACE'], os.environ['LOCALAPPDATA'], str(Path.home()), os.environ.get('USERNAME', '\0')]
    with zipfile.ZipFile(p1) as zf:
        for name in zf.namelist():
            text = zf.read(name).decode('latin-1')
            for s in secrets:
                for form in (s, s.replace('\\', '/'), s.replace('\\', '\\\\')):
                    if len(form) > 3:
                        assert form not in text, (name, form)


def make_zip(entries: dict[str, bytes], manifest=True, symlink=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        if manifest:
            files = [{'path': n, 'size': len(b), 'sha256': hashlib.sha256(b).hexdigest()} for n, b in entries.items()]
            zf.writestr('nscase.json', json.dumps({'format': 1, 'files': files}))
        for n, b in entries.items():
            zf.writestr(n, b)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = 0o120777 << 16
            zf.writestr(info, b'../../x')
    return buf.getvalue()


CASE = json.dumps({'case_id': 'c_20260101_000000_abcd', 'template': 'cantilever', 'revision': 1}).encode()


@pytest.mark.parametrize('entries,key', [
    ({'case.json': CASE, '../x.json': b'{}'}, 'err.archive_path'),
    ({'case.json': CASE, 'C:/x.json': b'{}'}, 'err.archive_path'),
    ({'case.json': CASE, '/x.json': b'{}'}, 'err.archive_path'),
    ({'case.json': CASE, 'run/r_1234/evil.exe': b'MZ'}, 'err.archive_path'),
    ({'case.json': CASE, 'mesh/big.json': b'0' * (5 * 1024 ** 2)}, 'err.archive_ratio'),
])
def test_malicious_archives_rejected(entries, key):
    before = sorted(p.name for p in store.cases_dir().iterdir())
    with pytest.raises(StudioError) as e:
        C.import_case(data=make_zip(entries), lang='en')
    assert e.value.key == key
    assert sorted(p.name for p in store.cases_dir().iterdir()) == before


def test_symlink_hash_and_count_rejected():
    with pytest.raises(StudioError) as e:
        C.import_case(data=make_zip({'case.json': CASE}, symlink='mesh/link.json'), lang='en')
    assert e.value.key in ('err.archive_path', 'err.archive_manifest')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('nscase.json', json.dumps({'format': 1, 'files': [{'path': 'case.json', 'size': len(CASE), 'sha256': '0' * 64}]}))
        zf.writestr('case.json', CASE)
    with pytest.raises(StudioError) as e:
        C.import_case(data=buf.getvalue(), lang='en')
    assert e.value.key == 'err.archive_hash'
    many = {f'mesh/f{i}.json': b'{}' for i in range(2001)} | {'case.json': CASE}
    with pytest.raises(StudioError) as e:
        C.import_case(data=make_zip(many), lang='en')
    assert e.value.key == 'err.archive_too_many'


def test_newer_format_refused():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('nscase.json', json.dumps({'format': 99, 'studio_version': '9.0.0', 'files': []}))
    with pytest.raises(StudioError) as e:
        C.import_case(data=buf.getvalue(), lang='en')
    assert e.value.key == 'err.archive_newer'


@pytest.fixture
def server(tmp_path):
    root = tmp_path / 'site'; root.mkdir()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    os.environ['NOVASTUDIO_EXAMPLES_URL'] = f'http://127.0.0.1:{httpd.server_address[1]}/'
    yield root, httpd
    httpd.shutdown()
    os.environ.pop('NOVASTUDIO_EXAMPLES_URL', None)
    import shutil
    shutil.rmtree(examples.cache_dir(), ignore_errors=True)


def publish(root: Path):
    src = Path(C.export_case(solved(), lang='en')['path'])
    data = src.read_bytes()
    (root / 'example-plastic-bar.nscase').write_bytes(data)
    idx = {'format': 1, 'studio_version': '0.6.1', 'examples': [{
        'name': 'plastic-bar', 'template': 'plastic-bar', 'physics': 'structural', 'file': 'example-plastic-bar.nscase',
        'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'title': {'en': 'Bar', 'ja': '棒', 'zh': '杆'},
        'reference': {'label': {'en': 'ref'}, 'value': 268, 'unit': 'MPa'}, 'result': {'value': 268, 'unit': 'MPa'}, 'error_pct': 0.0}]}
    (root / 'examples.json').write_text(json.dumps(idx), encoding='utf-8')
    return data


def test_examples_list_open_and_cache(server):
    root, httpd = server
    publish(root)
    listed = C.list_examples(lang='ja')
    assert not listed['offline'] and listed['examples'][0]['title'] == '棒'
    p = C.open_example('plastic-bar', lang='en')
    assert store.load(p['case']['case_id'])['provenance']['imported_from']['example'] == 'plastic-bar'
    assert not C.verify_case(p['case']['case_id'], lang='en')['stale']
    httpd.shutdown(); httpd.server_close()
    offline = C.list_examples(lang='en')            # the cached index still works offline
    assert offline['offline'] and offline['examples'][0]['cached']
    C.open_example('plastic-bar', lang='en')        # and so does the cached archive


def test_examples_offline_without_cache_and_bad_input(server):
    root, httpd = server
    httpd.shutdown(); httpd.server_close()
    for lang in ('ja', 'en', 'zh'):
        with pytest.raises(StudioError) as e:
            C.list_examples(lang=lang)
        assert e.value.key == 'err.examples_offline'
        msg = C.error_payload(e.value, lang)
        assert 'github.com/novasolver' in json.dumps(msg, ensure_ascii=False)
    for name in ('../x', 'http://evil', 'A'):
        with pytest.raises(StudioError) as e:
            examples.entry(name)
        assert e.value.key == 'err.example_unknown'


def test_build_examples_index_matches_verification(tmp_path):
    import subprocess, sys
    root = Path(__file__).resolve().parents[2]
    env = {k: v for k, v in os.environ.items() if k not in ('NOVASTUDIO_WORKSPACE', 'LOCALAPPDATA')}
    r = subprocess.run([sys.executable, str(root / 'tools' / 'build_examples.py'), '--only', 'cantilever,plastic-bar',
                        '--out', str(tmp_path)], capture_output=True, text=True, env=env, timeout=900)
    assert r.returncode == 0, r.stdout + r.stderr
    out = next(tmp_path.iterdir())
    idx = json.loads((out / 'examples.json').read_text(encoding='utf-8'))
    assert [e['name'] for e in idx['examples']] == ['cantilever', 'plastic-bar']
    for e in idx['examples']:
        assert hashlib.sha256((out / e['file']).read_bytes()).hexdigest() == e['sha256']
        assert set(e['title']) == {'ja', 'en', 'zh'} and set(e['reference']['label']) == {'ja', 'en', 'zh'}
    ver = C.verify_case(solved(), lang='en')['verification']
    bar = idx['examples'][1]
    assert bar['error_pct'] == pytest.approx(ver['error_pct'], abs=1e-9)
    assert bar['result']['value'] == pytest.approx(ver['computed'], rel=1e-12)
    # the build ran in its own folders: nothing was added to this workspace
    assert not list((Path(os.environ['NOVASTUDIO_WORKSPACE']) / 'cases').glob('*/exports/example-*'))


def test_examples_hash_mismatch_deletes(server):
    root, _ = server
    publish(root)
    (root / 'example-plastic-bar.nscase').write_bytes(b'tampered')
    with pytest.raises(StudioError) as e:
        C.open_example('plastic-bar', lang='en')
    assert e.value.key == 'err.example_corrupt'
    assert not (examples.cache_dir() / 'example-plastic-bar.nscase').exists()
