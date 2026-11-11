"""Verify this metadata-only post-release against the published 0.7.6 wheel."""
import email
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile

with urllib.request.urlopen('https://pypi.org/pypi/novasolver-studio/0.7.6/json', timeout=60) as response:
    release = json.load(response)
wheel = next(item for item in release['urls'] if item['filename'].endswith('.whl'))
with urllib.request.urlopen(wheel['url'], timeout=60) as response:
    baseline = response.read()
assert hashlib.sha256(baseline).hexdigest() == wheel['digests']['sha256']
candidate = Path('dist-py/novasolver_studio-0.7.6.post1-py3-none-any.whl')
with zipfile.ZipFile(io.BytesIO(baseline)) as old, zipfile.ZipFile(candidate) as new:
    old_files = {n for n in old.namelist() if n.startswith('novastudio/')}
    new_files = {n for n in new.namelist() if n.startswith('novastudio/')}
    assert old_files == new_files, 'Package file set changed'
    changed = sorted(n for n in old_files if old.read(n) != new.read(n))
    assert changed == ['novastudio/__init__.py'], changed
    assert old.read(changed[0]).replace(b'"0.7.6"', b'"0.7.6.post1"') == new.read(changed[0])
    metadata = email.message_from_bytes(new.read(next(n for n in new.namelist() if n.endswith('/METADATA'))))
    assert metadata['Version'] == '0.7.6.post1'
    assert metadata['Author-email'] == 'NovaSolver <info@novasolver.jp>'
    assert 'mcp-name: io.github.novasolver/novasolver-studio' in metadata.get_payload()
print('PASS: all package resources/code identical except version; ownership marker and author verified.')
