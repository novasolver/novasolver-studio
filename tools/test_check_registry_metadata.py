import copy
import json
import tempfile
import unittest
from pathlib import Path

from check_registry_metadata import check, check_published

ROOT = Path(__file__).resolve().parents[1]


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'backend/novastudio').mkdir(parents=True)
        for name in ('README.md', 'backend/novastudio/__init__.py'):
            (self.root / name).write_bytes((ROOT / name).read_bytes())
        self.data = json.loads((ROOT / 'server.json').read_text())

    def write(self, alternate=None):
        (self.root / 'server.json').write_text(json.dumps(self.data), encoding='utf-8')
        (self.root / 'server.pypi.json').write_text(
            json.dumps(self.data if alternate is None else alternate), encoding='utf-8')

    def test_current_pair_passes(self):
        self.write()
        check(self.root)

    def test_missing_pypi_is_rejected(self):
        self.data['packages'] = [p for p in self.data['packages'] if p['registryType'] != 'pypi']
        self.write()
        with self.assertRaisesRegex(ValueError, 'both'):
            check(self.root)

    def test_missing_mcp_subcommand_is_rejected(self):
        next(p for p in self.data['packages'] if p['registryType'] == 'pypi').pop('packageArguments')
        self.write()
        with self.assertRaisesRegex(ValueError, 'packageArguments'):
            check(self.root)

    def test_stale_pypi_version_is_rejected(self):
        next(p for p in self.data['packages'] if p['registryType'] == 'pypi')['version'] = '0.4.1'
        self.write()
        with self.assertRaisesRegex(ValueError, 'version'):
            check(self.root)

    def test_stale_template_is_rejected(self):
        alternate = copy.deepcopy(self.data)
        alternate['version'] = '0.4.1'
        self.write(alternate)
        with self.assertRaisesRegex(ValueError, 'template'):
            check(self.root)

    def test_public_readme_missing_marker_is_rejected(self):
        package = next(p for p in self.data['packages'] if p['registryType'] == 'pypi')
        public = {'info': {'version': package['version'], 'description': 'MCP-enabled engineering software'}}
        with self.assertRaisesRegex(ValueError, 'ownership marker'):
            check_published(self.data, lambda _: public)

    def test_public_readme_comment_marker_passes(self):
        package = next(p for p in self.data['packages'] if p['registryType'] == 'pypi')
        public = {'info': {'version': package['version'],
                  'description': '<!-- mcp-name: io.github.novasolver/novasolver-studio -->'}}
        check_published(self.data, lambda _: public)


if __name__ == '__main__':
    unittest.main()
