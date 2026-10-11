"""Portable delivery boundary checks, using only synthetic payloads."""
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.install_windows import allowed_payload, verify_bundle
from library_transfer import _digest


class WindowsDeliveryTests(unittest.TestCase):
    def test_launcher_uses_quoted_local_powershell_without_global_policy_change(self):
        path = Path(__file__).resolve().parents[1] / 'scripts/install_windows.cmd'
        self.assertTrue(path.is_file(), 'Double-click launcher missing')
        text = path.read_text()
        self.assertIn('"%~dp0windows_bootstrap.ps1"', text)
        self.assertIn('-NoProfile', text)
        self.assertNotIn('Set-ExecutionPolicy', text)

    def test_plugin_selection_preserves_explicit_connection_manifest(self):
        builder = self.builder()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.mcp.json').write_text('{"mcpServers":{}}')
            (root / '.secret.json').write_text('synthetic secret')
            self.assertEqual(set(builder.tree_files(root, 'plugins/chiheng-legal')),
                             {'plugins/chiheng-legal/.mcp.json'})

    def builder(self):
        self.assertIsNotNone(importlib.util.find_spec('scripts.build_windows_delivery'),
                             'Windows delivery builder is missing')
        return importlib.import_module('scripts.build_windows_delivery')

    def test_only_exact_extra_test_assets_and_dev_wheels_are_allowed(self):
        for name in ('source/dist/cn-litigation-redteam.zip', 'source/upstream/original/LICENSE',
                     'source/upstream/original/NOTICE', 'runtime/wheels-dev/reportlab-4.4.9-py3-none-any.whl'):
            self.assertTrue(allowed_payload(name))
        for name in ('source/upstream/original/server.py', 'source/dist/other.zip',
                     'source/config/local-machine.json', 'runtime/wheels-dev/script.py'):
            with self.assertRaises(ValueError):
                allowed_payload(name)

    def test_secret_session_and_machine_files_never_selected(self):
        builder = self.builder()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('legal_mcp.py', 'tests/test_ok.py', 'tests/.env',
                         'tests/session.json', 'tests/cookies.json', 'tests/.venv/bad.py',
                         'tests/behavior/runs/private.json', 'config/local-machine.json'):
                p = root / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text('synthetic')
            files = builder.select_source(root)
            self.assertEqual(set(files), {'source/legal_mcp.py', 'source/tests/test_ok.py'})

    def test_source_change_between_selection_and_copy_is_refused(self):
        builder = self.builder()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'test.py'
            source.write_text('before')
            expected = _digest(source)
            source.write_text('after')
            with self.assertRaisesRegex(ValueError, 'changed'):
                builder.copy_checked(source, root / 'out.py', expected)

    def test_symlink_source_is_refused(self):
        builder = self.builder()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'real').write_text('synthetic')
            try:
                (root / 'bad.py').symlink_to(root / 'real')
            except OSError:
                self.skipTest('host does not permit synthetic symlink')
            with self.assertRaises(ValueError):
                builder.select_source(root)

    def test_manifest_rejects_changed_and_undeclared_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            names = ('source/scripts/install_windows.py', 'source/legal_mcp.py',
                     'source/requirements-windows.lock.txt', 'data/personal-public-library.zip',
                     'runtime/python-3.13.16-amd64.zip')
            for name in names:
                p = root / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text('synthetic')
            (root / 'manifest.json').write_text(json.dumps({'schema_version': 1,
                'files': {name: _digest(root / name) for name in names}}))
            verify_bundle(root)
            (root / names[0]).write_text('changed')
            with self.assertRaises(ValueError):
                verify_bundle(root)
            (root / names[0]).write_text('synthetic')
            (root / 'source/extra.py').write_text('extra')
            with self.assertRaises(ValueError):
                verify_bundle(root)

    def test_yaml_loader_is_python_only_and_refuses_aliases_and_objects(self):
        from tests.test_p1 import load_yaml
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.yaml'
            path.write_text('value: 中文\n')
            with patch('subprocess.run', side_effect=AssertionError('external YAML runtime')):
                self.assertEqual(load_yaml(path), {'value': '中文'})
            for text in ('a: &a [1]\nb: *a\n', '!!python/object:builtins.object {}',
                         'date: 2020-01-01\n', 'value: !!set {a: null}\n', 'value: .inf\n'):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    load_yaml(path)

    def test_vendor_recovery_fixture_uses_packaged_source_and_private_startup(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        try:
            import test_rmfyalk_recovery as recovery
            self.assertTrue(recovery.UPSTREAM.is_relative_to(Path(__file__).resolve().parents[1] / 'vendor'))
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'private' / 'case-access.env'
                recovery.write_credentials(path)
                client = recovery.load_client(path)
                self.assertEqual(Path(client.DEFAULT_CREDENTIAL_PATH), path)
        finally:
            sys.path.pop(0)
