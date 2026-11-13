"""Before publishing a .postN wheel, require unchanged application bytes except version."""
import email
import hashlib
import io
import json
from pathlib import Path
import re
import urllib.request
import zipfile


def verify(baseline, candidate, base, version):
    with zipfile.ZipFile(io.BytesIO(baseline)) as old, zipfile.ZipFile(candidate) as new:
        old_files = {n for n in old.namelist() if n.startswith('novastudio/')}
        new_files = {n for n in new.namelist() if n.startswith('novastudio/')}
        if old_files != new_files:
            raise ValueError('Package file set changed')
        changed = sorted(n for n in old_files if old.read(n) != new.read(n))
        if changed != ['novastudio/__init__.py']:
            raise ValueError(f'Application or resource changes detected: {changed}')
        old_init = old.read(changed[0])
        expected = old_init.replace(f'__version__ = "{base}"'.encode(), f'__version__ = "{version}"'.encode())
        if expected == old_init or expected != new.read(changed[0]):
            raise ValueError('Version module has unrelated changes')
        def metadata(archive):
            return email.message_from_bytes(archive.read(next(n for n in archive.namelist() if n.endswith('.dist-info/METADATA'))))
        previous, current = metadata(old), metadata(new)
        if previous['Version'] != base or current['Version'] != version:
            raise ValueError('Wheel metadata version mismatch')
        for key in ('Name', 'Requires-Python', 'Requires-Dist', 'Provides-Extra', 'License-Expression'):
            if previous.get_all(key) != current.get_all(key):
                raise ValueError(f'Unexpected package metadata change: {key}')
        if current['Author-email'] != 'NovaSolver <info@novasolver.jp>':
            raise ValueError('Unexpected public author')
        if 'mcp-name: io.github.novasolver/novasolver-studio' not in current.get_payload():
            raise ValueError('Missing ownership marker')
        for filename in ('entry_points.txt', 'WHEEL'):
            def read(archive):
                return archive.read(next(n for n in archive.namelist() if n.endswith('.dist-info/' + filename)))
            if read(old) != read(new):
                raise ValueError(f'Unexpected launcher or compatibility change: {filename}')


def main():
    wheels = list(Path('dist-py').glob('*.whl'))
    if len(wheels) != 1:
        raise ValueError('Expected exactly one candidate wheel')
    candidate = wheels[0]
    with zipfile.ZipFile(candidate) as archive:
        metadata = email.message_from_bytes(archive.read(next(n for n in archive.namelist() if n.endswith('.dist-info/METADATA'))))
    version = metadata['Version']
    match = re.fullmatch(r'(.+)\.post\d+', version)
    if not match:
        print('Regular release: metadata-only post-release comparison not applicable')
        return
    base = match.group(1)
    with urllib.request.urlopen(f'https://pypi.org/pypi/novasolver-studio/{base}/json', timeout=60) as response:
        release = json.load(response)
    wheel = next(item for item in release['urls'] if item['filename'].endswith('.whl'))
    with urllib.request.urlopen(wheel['url'], timeout=60) as response:
        baseline = response.read()
    if hashlib.sha256(baseline).hexdigest() != wheel['digests']['sha256']:
        raise ValueError('Published baseline SHA-256 mismatch')
    verify(baseline, candidate, base, version)
    print('PASS: unchanged application/resources, dependencies and launchers; version/ownership/author verified')


if __name__ == '__main__':
    main()
