import importlib.util
from pathlib import Path
import tempfile
import tomllib
import unittest

spec = importlib.util.spec_from_file_location('configure_codex_mcp', Path(__file__).with_name('configure_codex_mcp.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ConfigTests(unittest.TestCase):
    def test_preserves_unrelated_bytes_and_unicode(self):
        before = '\ufeff# 日本語\r\n[mcp_servers.other]\r\ncommand="other"\r\n'.encode('utf-8')
        after = module.plan(before)
        self.assertTrue(after.startswith(before))
        self.assertEqual(tomllib.loads(after.decode('utf-8-sig'))['mcp_servers']['other']['command'], 'other')
        self.assertNotIn(b'\n', after.replace(b'\r\n', b''))

    def test_existing_custom_policy_is_preserved(self):
        before = (module.TABLE + 'enabled = false\ndefault_tools_approval_mode = "prompt"\n').encode()
        self.assertEqual(module.plan(before), before)

    def test_refuses_conflict_and_invalid_toml(self):
        for before in [b'[mcp_servers.novasolver-studio]\ncommand="different"\n', b'[broken', b'mcp_servers=42']:
            with self.assertRaises(ValueError):
                module.plan(before)

    def test_dry_run_has_no_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'new' / 'config.toml'
            module.configure(path)
            self.assertFalse(path.parent.exists())

    def test_backup_and_idempotency(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.toml'
            original = b'# retained\nmodel = "existing-model"\n'
            path.write_bytes(original)
            module.configure(path, True)
            after = path.read_bytes()
            backups = list(path.parent.glob('*.novasolver-backup-*'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)
            self.assertEqual(tomllib.loads(after.decode())['model'], 'existing-model')
            module.configure(path, True)
            self.assertEqual(path.read_bytes(), after)
            self.assertEqual(len(list(path.parent.glob('*.novasolver-backup-*'))), 1)

    def test_busy_lock_leaves_original_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.toml'
            path.write_bytes(b'# original\n')
            lock = path.with_name(path.name + '.novasolver.lock')
            lock.touch()
            with self.assertRaises(FileExistsError):
                module.configure(path, True)
            self.assertEqual(path.read_bytes(), b'# original\n')
            self.assertTrue(lock.exists())


if __name__ == '__main__':
    unittest.main()
