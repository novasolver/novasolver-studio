"""Case archives (.nscase): one zip holding a case, its mesh and its latest finished result.

Export is deterministic (sorted entries, fixed timestamps), so the same solved case always gives the same sha256;
the published examples are checked against that hash. Import trusts nothing in the zip: every entry is checked
against an allowlist and the manifest's sha256 before anything is written next to the user's cases."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import secrets
import shutil
import time
import zipfile
from pathlib import Path

from . import __version__, store
from .config import data_dir, workspace
from .store import StudioError

FORMAT = 1
MAX_ENTRIES = 2000
MAX_TOTAL = 2 * 1024 ** 3
MAX_RATIO = 200
EPOCH = (2026, 1, 1, 0, 0, 0)
TEXT = ('.json', '.log', '.txt')
SUFFIXES = TEXT + ('.npz', '.msh', '.step', '.stp', '.stl', '.brep', '.iges', '.igs')
# of_location.txt points at a scratch folder on the solving machine; STOP and *.tmp are run-time debris
SKIP = {'of_location.txt', 'STOP', '.lock'}
_JOB = r'r_[0-9a-z_]{4,40}'
_ALLOWED = re.compile(rf'^(nscase\.json|case\.json|(geom|mesh|geometry)/[A-Za-z0-9_.-]+'
                      rf'|run/{_JOB}/(levels/(coarse|normal|fine)/(mesh/)?)?[A-Za-z0-9_.-]+)$')


def _slug(case: dict) -> str:
    title = case.get('title', {}).get('en') or case['template']
    return re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:40] or 'case'


def _private_paths() -> list[tuple[str, str]]:
    """Machine paths that must not leave the PC, longest first so the workspace wins over the home folder."""
    pairs = [(str(workspace()), '<workspace>'), (str(data_dir()), '<data>'), (str(Path.home()), '<home>')]
    out = []
    for p, tag in pairs:
        for form in {p, p.replace('\\', '/'), p.replace('\\', '\\\\'), json.dumps(p)[1:-1]}:
            if len(form) > 3:
                out.append((form, tag))
    return sorted(out, key=lambda x: -len(x[0]))


def _scrub(text: str) -> str:
    for p, tag in _private_paths():
        text = text.replace(p, tag)
    return text


def _run_files(jd: Path) -> list[Path]:
    return [f for f in sorted(jd.rglob('*')) if f.is_file() and f.name not in SKIP and f.suffix.lower() in SUFFIXES]


def _finished_run(d: Path) -> Path | None:
    from . import jobs
    for jd in sorted((d / 'run').glob('r_*'), reverse=True):
        if (jd / 'results.json').is_file() and (jd / 'job.json').is_file() and jobs.read(jd).get('state') == 'done':
            return jd
    return None


def _member(name: str, data: bytes, zf: zipfile.ZipFile) -> None:
    info = zipfile.ZipInfo(name, EPOCH)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    zf.writestr(info, data, compresslevel=6)


def export_case(case_id: str, include_results: bool = True, verification: dict | None = None) -> Path:
    d = store.case_dir(case_id)
    case = store.load(case_id)
    files: dict[str, bytes] = {}
    for sub in ('geom', 'mesh', 'geometry'):
        for f in sorted((d / sub).glob('*')) if (d / sub).is_dir() else []:
            if f.is_file() and f.name not in SKIP and f.suffix.lower() in SUFFIXES:
                files[f'{sub}/{f.name}'] = f.read_bytes()
    created = case.get('provenance', {}).get('created_at') or ''
    jd = _finished_run(d) if include_results else None
    if jd is not None:
        for f in _run_files(jd):
            files['run/' + f.relative_to(d / 'run').as_posix()] = f.read_bytes()
        job = json.loads((jd / 'job.json').read_text(encoding='utf-8'))
        job.update(pid=None, pid_ctime=None)
        files[f'run/{jd.name}/job.json'] = json.dumps(job, ensure_ascii=False, indent=1).encode()
        created = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(job.get('updated_at') or job.get('created_at') or 0))
    files['case.json'] = json.dumps(case, ensure_ascii=False, indent=1).encode()
    for name in list(files):
        if name.endswith(TEXT):
            files[name] = _scrub(files[name].decode('utf-8', errors='replace')).encode('utf-8')
    manifest = {'format': FORMAT, 'studio_version': __version__, 'template': case['template'],
                'physics': case.get('physics', {}).get('kind'), 'created_at': created,
                'case_id': case_id, 'run_id': jd.name if jd is not None else None,
                'files': [{'path': n, 'size': len(b), 'sha256': hashlib.sha256(b).hexdigest()} for n, b in sorted(files.items())]}
    if verification is not None:
        manifest['verification'] = verification
    folder = d / 'exports'
    folder.mkdir(exist_ok=True)
    target = folder / f'{_slug(case)}-{case_id}.nscase'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        _member('nscase.json', json.dumps(manifest, ensure_ascii=False, indent=1).encode(), zf)
        for name in sorted(files):
            _member(name, files[name], zf)
    tmp = target.with_suffix(f'.{secrets.token_hex(4)}.tmp')
    tmp.write_bytes(buf.getvalue())
    os.replace(tmp, target)
    return target


def _invalid(reason: str, **kw):
    raise StudioError('err.archive_' + reason, 400, **kw)


def read_manifest(zf: zipfile.ZipFile) -> dict:
    infos = zf.infolist()
    if len(infos) > MAX_ENTRIES:
        _invalid('too_many', count=len(infos))
    total = 0
    for i in infos:
        name = i.filename
        if (name.startswith(('/', '\\')) or '\\' in name or ':' in name or '..' in name.split('/')
                or not _ALLOWED.match(name) or not name.lower().endswith(SUFFIXES)):
            _invalid('path', path=name[:120])
        if (i.external_attr >> 16) & 0o170000 == 0o120000:        # symlink
            _invalid('path', path=name[:120])
        total += i.file_size
        if i.file_size > MAX_RATIO * max(i.compress_size, 1) and i.file_size > 1024 ** 2:
            _invalid('ratio', path=name[:120])
    if total > MAX_TOTAL:
        _invalid('size')
    try:
        manifest = json.loads(zf.read('nscase.json'))
    except (KeyError, ValueError):
        _invalid('manifest')
    if not isinstance(manifest, dict) or not isinstance(manifest.get('format'), int):
        _invalid('manifest')
    if manifest['format'] > FORMAT:
        raise StudioError('err.archive_newer', 400, version=str(manifest.get('studio_version', '?')))
    listed = {f.get('path'): f for f in manifest.get('files', []) if isinstance(f, dict)}
    names = {i.filename for i in infos} - {'nscase.json'}
    if set(listed) != names or 'case.json' not in names:
        _invalid('manifest')
    return manifest


def import_case(path: str | None = None, data: bytes | None = None, example: str | None = None) -> tuple[str, list[str]]:
    """Returns the new case id and warning keys."""
    if data is None:
        if not path or not Path(path).is_file():
            raise StudioError('err.cad_missing', 404, path=Path(path or '').name)
        data = Path(path).read_bytes()
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        _invalid('zip')
    with zf:
        manifest = read_manifest(zf)
        contents = {}
        for f in manifest['files']:
            b = zf.read(f['path'])
            if len(b) != f.get('size') or hashlib.sha256(b).hexdigest() != f.get('sha256'):
                _invalid('hash', path=f['path'][:120])
            contents[f['path']] = b
    from .templates import TEMPLATES
    try:
        case = json.loads(contents['case.json'])
        old = case['case_id']
        ok = (store._ID.match(old) and case['template'] in TEMPLATES and isinstance(case['revision'], int)
              and all(isinstance(case.get(k), dict) for k in ('geometry', 'physics', 'materials', 'boundaries', 'mesh', 'run')))
    except (ValueError, KeyError, TypeError):
        ok = False
    if not ok:
        _invalid('manifest')
    new = store.new_id()
    while (store.cases_dir() / new).exists():
        new = store.new_id()
    runs = sorted({p.split('/')[1] for p in contents if p.startswith('run/')})
    job_ids = {r: 'r_' + time.strftime('%Y%m%d_%H%M%S') + '_' + secrets.token_hex(2) for r in runs}
    warnings = []

    def rename(b: bytes) -> bytes:
        s = b.decode('utf-8', errors='replace').replace(old, new)
        for a, z in job_ids.items():
            s = s.replace(a, z)
        return s.encode('utf-8')

    staging = store.cases_dir() / f'.import_{secrets.token_hex(6)}'
    try:
        for name, b in contents.items():
            if name == 'nscase.json':
                continue
            if name.startswith('run/'):
                parts = name.split('/')
                parts[1] = job_ids[parts[1]]
                name = '/'.join(parts)
            if name.endswith(TEXT):
                b = rename(b)
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b)
        (staging / 'revisions').mkdir(exist_ok=True)
        case = json.loads((staging / 'case.json').read_text(encoding='utf-8'))
        case.setdefault('provenance', {})['imported_from'] = {
            'case_id': old, 'studio_version': manifest.get('studio_version'), 'example': example}
        (staging / 'case.json').write_text(json.dumps(case, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(staging, store.cases_dir() / new)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    # A result written by an older solver that no longer loads is dropped, the case itself stays usable.
    try:
        from . import results
        if runs:
            results.payload(store.load(new), 'en')
    except Exception:
        shutil.rmtree(store.cases_dir() / new / 'run', ignore_errors=True)
        warnings.append('warn.archive_results_dropped')
    return new, warnings
