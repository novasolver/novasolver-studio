"""Solved examples: verification cases solved once and published as GitHub release assets.

Only the configured base URL is fetched, and only names listed in its index, so a tool argument cannot point the
app at another host or file. Downloads are checked against the index's sha256 before import."""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import urllib.error
import urllib.request
from pathlib import Path

from . import __version__
from .config import data_dir
from .store import StudioError

EXAMPLES_BASE = 'https://github.com/novasolver/novasolver-studio/releases/download/v{version}/'
RELEASE_PAGE = 'https://github.com/novasolver/novasolver-studio/releases/tag/v{version}'
INDEX = 'examples.json'
TIMEOUT = 10
_NAME = re.compile(r'^[a-z0-9-]{1,60}$')


def base_url() -> str:
    url = os.environ.get('NOVASTUDIO_EXAMPLES_URL') or EXAMPLES_BASE.format(version=__version__)
    return url if url.endswith('/') else url + '/'


def release_page() -> str:
    return RELEASE_PAGE.format(version=__version__)


def cache_dir() -> Path:
    d = data_dir() / 'examples' / __version__
    d.mkdir(parents=True, exist_ok=True)
    return d


def _fetch(name: str, progress=None) -> bytes:
    req = urllib.request.Request(base_url() + name, headers={'User-Agent': f'NovaSolverStudio/{__version__}'})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        total = int(r.headers.get('Content-Length') or 0)
        chunks, got = [], 0
        while True:
            b = r.read(1 << 16)
            if not b:
                break
            chunks.append(b); got += len(b)
            if progress and total > 1 << 20:
                progress(got, total)
    return b''.join(chunks)


def _write(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + f'.{secrets.token_hex(4)}.tmp')
    tmp.write_bytes(data)
    os.replace(tmp, path)


def index() -> dict:
    cached = cache_dir() / INDEX
    try:
        data = _fetch(INDEX)
        parsed = json.loads(data)
        if not isinstance(parsed, dict) or not isinstance(parsed.get('examples'), list):
            raise ValueError('index')
        _write(cached, data)
        return {**parsed, 'offline': False}
    except (OSError, ValueError) as e:
        if cached.is_file():
            return {**json.loads(cached.read_text(encoding='utf-8')), 'offline': True}
        # reachable but not published (a release without examples, or a development version): not "offline"
        if isinstance(e, urllib.error.HTTPError) and e.code == 404:
            raise StudioError('err.examples_missing', 404, url=release_page())
        raise StudioError('err.examples_offline', 503, url=release_page())


def entry(name: str) -> tuple[dict, dict]:
    if not isinstance(name, str) or not _NAME.match(name):
        raise StudioError('err.example_unknown', 404, name=str(name)[:60])
    idx = index()
    for e in idx['examples']:
        if e.get('name') == name:
            if not (isinstance(e.get('file'), str) and re.match(r'^[a-z0-9-]+\.nscase$', e['file'])
                    and re.match(r'^[0-9a-f]{64}$', str(e.get('sha256', '')))):
                raise StudioError('err.example_corrupt', 502, name=name)
            return idx, e
    raise StudioError('err.example_unknown', 404, name=name)


def fetch_archive(name: str, progress=None) -> Path:
    _, e = entry(name)
    path = cache_dir() / e['file']
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == e['sha256']:
        return path
    try:
        data = _fetch(e['file'], progress)
    except OSError:
        raise StudioError('err.examples_offline', 503, url=release_page())
    if hashlib.sha256(data).hexdigest() != e['sha256']:
        path.unlink(missing_ok=True)
        raise StudioError('err.example_corrupt', 502, name=name)
    _write(path, data)
    return path


def localized(e: dict, lang: str) -> dict:
    pick = lambda v: v.get(lang) or v.get('en') if isinstance(v, dict) else v
    ref = e.get('reference') or {}
    return {'name': e['name'], 'template': e.get('template'), 'physics': e.get('physics'),
            'title': pick(e.get('title', {})), 'description': pick(e.get('description', {})),
            'size': e.get('size'), 'error_pct': e.get('error_pct'),
            'reference': {'label': pick(ref.get('label', {})), 'value': ref.get('value'), 'unit': ref.get('unit')},
            'result': e.get('result'), 'mesh': e.get('mesh'), 'solve_s': e.get('solve_s'),
            'cached': (cache_dir() / str(e.get('file', ''))).is_file()}
