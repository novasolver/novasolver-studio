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
import zlib
from pathlib import Path

from . import __version__, store
from .config import data_dir, workspace
from .store import StudioError

FORMAT = 1
MAX_ENTRIES = 2000
MAX_TOTAL = 1024 ** 3                  # held in memory while checked; the largest solved example is ~10 MB
MAX_RATIO = 200
EPOCH = (2026, 1, 1, 0, 0, 0)
TEXT = ('.json', '.log', '.txt')
SUFFIXES = TEXT + ('.npz', '.msh', '.step', '.stp', '.stl', '.brep', '.iges', '.igs')
# of_location.txt points at a scratch folder on the solving machine; STOP and *.tmp are run-time debris
SKIP = {'of_location.txt', 'STOP', '.lock'}
_JOB = r'r_[0-9a-z_]{4,40}'
_ALLOWED = re.compile(rf'^(nscase\.json|case\.json|(geom|mesh|geometry)/[A-Za-z0-9_.-]+'
                      rf'|run/{_JOB}/(levels/(coarse|normal|fine)/(mesh/)?)?[A-Za-z0-9_.-]+)$')
# Windows opens these as devices whatever the extension: geom/CON.json would write to the console, not a file.
_RESERVED = re.compile(r'^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$', re.I)
CAD_FILE = re.compile(r'^geometry/[A-Za-z0-9_.-]+\.(step|stp|iges|igs|brep|stl)$', re.I)


def allowed(name: str) -> bool:
    return (bool(_ALLOWED.match(name)) and name.lower().endswith(SUFFIXES) and '..' not in name.split('/')
            and not any(_RESERVED.match(part) for part in name.split('/')))


_STEP_FILE_NAME = re.compile(rb"FILE_NAME\s*\(.*?\)\s*;", re.S)


def anonymous_step(data: bytes) -> bytes:
    """CAD systems write the original full path, author and organisation into the STEP header."""
    head, sep, body = data.partition(b'ENDSEC;')
    if not sep:
        return data
    head = _STEP_FILE_NAME.sub(b"FILE_NAME('model.step','',(''),(''),'','','');", head, count=1)
    return head + sep + body


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
    info.create_system = 0                         # the same bytes from Windows and POSIX
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
        created = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(job.get('updated_at') or job.get('created_at') or 0))
    files['case.json'] = json.dumps(case, ensure_ascii=False, indent=1).encode()
    # Only what import accepts (an engine's own subfolder such as run/<id>/ccx/ would make the archive unopenable).
    files = {n: b for n, b in files.items() if allowed(n)}
    for name in list(files):
        if name.endswith(TEXT):
            files[name] = _scrub(files[name].decode('utf-8', errors='replace')).encode('utf-8')
        elif CAD_FILE.match(name) and name.lower().endswith(('.step', '.stp')):
            files[name] = anonymous_step(files[name])
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
    seen = set()
    for i in infos:
        name = i.filename
        if name.startswith(('/', '\\')) or '\\' in name or ':' in name or not allowed(name):
            _invalid('path', path=name[:120])
        if name.casefold() in seen:                                # mesh/key.txt and mesh/KEY.txt are one file on Windows
            _invalid('path', path=name[:120])
        seen.add(name.casefold())
        if (i.external_attr >> 16) & 0o170000 == 0o120000:        # symlink
            _invalid('path', path=name[:120])
        total += i.file_size
        if i.file_size > MAX_RATIO * max(i.compress_size, 1) and i.file_size > 1024 ** 2:
            _invalid('ratio', path=name[:120])
    if total > MAX_TOTAL:
        _invalid('size')
    try:
        manifest = json.loads(_read(zf, 'nscase.json', 4 * 1024 ** 2))
    except (KeyError, ValueError):
        _invalid('manifest')
    if not isinstance(manifest, dict) or not isinstance(manifest.get('format'), int):
        _invalid('manifest')
    if manifest['format'] > FORMAT:
        raise StudioError('err.archive_newer', 400, version=str(manifest.get('studio_version', '?')))
    files = manifest.get('files')
    if not isinstance(files, list) or not all(
            isinstance(f, dict) and isinstance(f.get('path'), str) and isinstance(f.get('size'), int)
            and 0 <= f['size'] <= MAX_TOTAL and isinstance(f.get('sha256'), str) for f in files):
        _invalid('manifest')
    listed = {f['path'] for f in files}
    names = {i.filename for i in infos} - {'nscase.json'}
    if listed != names or len(listed) != len(files) or 'case.json' not in names or sum(f['size'] for f in files) > MAX_TOTAL:
        _invalid('manifest')
    return manifest


def _read(zf: zipfile.ZipFile, name: str, limit: int) -> bytes:
    """Inflate in chunks, counting real bytes: the sizes in the zip headers are the sender's claim."""
    out, got = [], 0
    with zf.open(name) as fh:
        while True:
            chunk = fh.read(1 << 20)
            if not chunk:
                return b''.join(out)
            got += len(chunk)
            if got > limit:
                _invalid('size')
            out.append(chunk)


def import_case(path: str | None = None, data: bytes | None = None, example: str | None = None) -> tuple[str, list[str]]:
    """Returns the new case id and warning keys."""
    if data is None:
        if not path or not Path(path).is_file():
            raise StudioError('err.cad_missing', 404, path=Path(path or '').name)
        data = Path(path).read_bytes()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            manifest = read_manifest(zf)
            contents, total = {}, 0
            for f in manifest['files']:
                b = _read(zf, f['path'], f['size'])       # never more than the manifest promised
                total += len(b)
                if len(b) != f['size'] or hashlib.sha256(b).hexdigest() != f['sha256']:
                    _invalid('hash', path=f['path'][:120])
                contents[f['path']] = b
    except StudioError:
        raise
    except (zipfile.BadZipFile, zipfile.LargeZipFile, NotImplementedError, RuntimeError, EOFError, OSError,
            ValueError, zlib.error):
        _invalid('zip')
    from .templates import TEMPLATES
    try:
        case = json.loads(contents['case.json'])
        old = case['case_id']
        ok = (store._ID.match(old) and case['template'] in TEMPLATES and isinstance(case['revision'], int)
              and all(isinstance(case.get(k), dict) for k in ('geometry', 'physics', 'materials', 'boundaries', 'mesh', 'run')))
        # geometry.file is joined to the case folder by the mesher: an absolute or ../ value would read any file
        cad = case['geometry'].get('file') if ok else None
        if cad is not None and not (isinstance(cad, str) and CAD_FILE.match(cad) and cad in contents):
            ok = False
    except (ValueError, KeyError, TypeError, AttributeError):
        ok = False
    if not ok:
        _invalid('manifest')
    # Run-time keys (a convergence level's _mesh_dir) are paths of the sending machine.
    contents['case.json'] = json.dumps({k: v for k, v in case.items() if not k.startswith('_')}, ensure_ascii=False, indent=1).encode()
    new = store.new_id()
    while (store.cases_dir() / new).exists():
        new = store.new_id()
    runs = sorted({p.split('/')[1] for p in contents if p.startswith('run/')})
    job_ids = {r: 'r_' + time.strftime('%Y%m%d_%H%M%S') + '_' + secrets.token_hex(4) for r in runs}
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
