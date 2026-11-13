import io
from pathlib import Path
import tempfile
import unittest
import zipfile
from check_metadata_postrelease import verify


def wheel(version, *, changed=False, marker=True):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('novastudio/__init__.py', f'__version__ = "{version}"\n')
        z.writestr('novastudio/commands.py', 'tampered' if changed else 'application')
        prefix = f'novasolver_studio-{version}.dist-info/'
        z.writestr(prefix+'METADATA', 'Metadata-Version: 2.4\nName: novasolver-studio\n'
                   f'Version: {version}\nAuthor-email: NovaSolver <info@novasolver.jp>\n'
                   'Requires-Python: >=3.10\nRequires-Dist: numpy>=2\n\n'
                   + ('<!-- mcp-name: io.github.novasolver/novasolver-studio -->' if marker else ''))
        z.writestr(prefix+'entry_points.txt', '[console_scripts]\nnovasolver-studio = novastudio.__main__:main\n')
        z.writestr(prefix+'WHEEL', 'Wheel-Version: 1.0\nTag: py3-none-any\n')
    return buf.getvalue()


class PostreleaseTests(unittest.TestCase):
    def run_candidate(self, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'candidate.whl'
            path.write_bytes(wheel('0.8.0.post1', **kwargs))
            verify(wheel('0.8.0'), path, '0.8.0', '0.8.0.post1')

    def test_version_only_passes(self):
        self.run_candidate()

    def test_hidden_code_change_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Application or resource'):
            self.run_candidate(changed=True)

    def test_missing_marker_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'ownership marker'):
            self.run_candidate(marker=False)


if __name__ == '__main__':
    unittest.main()
