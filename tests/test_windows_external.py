"""Windows adapters: synthetic inputs; no real account or native Windows claims."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

# Standalone Mac tests use only the already downloaded pure-Python wheel.
# On the target, run this suite in .venv-mcp1, where dotenv is installed.
try:
    import dotenv
except ModuleNotFoundError:
    wheel = ROOT / 'verification/windows10-2026-10-09/wheels-mcp1/python_dotenv-1.2.2-py3-none-any.whl'
    if wheel.is_file():
        sys.path.insert(0, str(wheel))
        import dotenv
        sys.path.remove(str(wheel))


class ExternalTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('windows_external'), 'external adapter missing')
        import windows_external
        return windows_external

    def test_sdk1_isolated_offline_install_and_real_import(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)
            calls = []
            def run(command, **kwargs):
                calls.append([str(x) for x in command])
                return subprocess.CompletedProcess(command, 0, '{"sdk": "1.28.0", "fastmcp": true}', '')
            with patch('scripts.install_windows.run', side_effect=run):
                result = api.install_mcp1(target / 'bundle', target)
            self.assertEqual(result['status'], 'installed_import_verified')
            self.assertIn(str(target / '.venv-mcp1'), calls[0])
            self.assertIn('--no-index', calls[1])
            self.assertIn('--require-hashes', calls[1])
            self.assertIn(str(target / 'bundle/runtime/wheels-mcp1'), calls[1])
            self.assertIn('from mcp.server.fastmcp import FastMCP', calls[2][-1])
            self.assertNotIn('find_spec', calls[2][-1])
            self.assertFalse(any(str(target / '.venv/Scripts/python.exe') in call for call in calls))

    def test_component_failure_does_not_claim_external_ready(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(api, 'install_mcp1', side_effect=OSError('sensitive-output')), \
                    patch.object(api, 'install_browser', return_value={'status': 'installed_native_pending'}):
                report = api.install_components(Path(folder), Path(folder))
            self.assertEqual(report['mcp1']['status'], 'failed')
            self.assertFalse(report['ready_external'])
            self.assertEqual(report['flk']['status'], 'blocked')
            self.assertNotIn('sensitive-output', json.dumps(report))

    def test_connection_fragment_uses_final_sdk1_and_conflicts_are_read_only(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = root / 'config.toml'
            raw = '[mcp_servers.menglu_rmfyalk]\ncommand = "existing"\n'
            config.write_text(raw)
            self.assertEqual(api.host_conflicts(config), ['menglu_rmfyalk'])
            self.assertEqual(config.read_text(), raw)
            fragment = api.connection_fragment(root)
            self.assertIn(str(root / '.venv-mcp1/Scripts/python.exe'), fragment)
            self.assertIn('windows_case_access.py', fragment)
            self.assertIn('windows_flk_blocked.py', fragment)

    def test_flk_entry_stays_blocked_without_importing_vendor(self):
        path = ROOT / 'scripts/windows_flk_blocked.py'
        self.assertTrue(path.is_file(), 'blocked FLK entry missing')
        result = subprocess.run([sys.executable, '-B', str(path)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('blocked', result.stderr)
        self.assertNotIn('httpx', path.read_text())

    def test_case_default_and_global_client_use_private_target(self):
        self.assertTrue((ROOT / 'windows_case_access.py').is_file(), 'case adapter missing')
        import windows_case_access as api
        self.assertEqual(api.access_path(), ROOT / 'private/case-access.env')
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(api, 'access_path', return_value=Path(folder) / 'private/case-access.env'), \
                patch.dict(os.environ, {'RMFYALK_TOKEN': 'synthetic-never-fallback'}):
            module = api.load_client()
            expected = Path(folder) / 'private/case-access.env'
            self.assertEqual(module.DEFAULT_CREDENTIAL_PATH, expected)
            self.assertEqual(module.client.credential_path, expected)
            with self.assertRaises(module.CredentialError) as raised:
                module.client.token
            self.assertEqual(raised.exception.kind, 'missing')
            self.assertNotIn('synthetic-never-fallback', str(raised.exception))

    def test_startup_never_reads_vendor_decoy_env(self):
        import windows_case_access as api
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scripts = root / 'vendor/component/scripts'
            scripts.mkdir(parents=True)
            shutil.copyfile(api.CASE_SCRIPTS / 'client.py', scripts / 'client.py')
            decoy = scripts.parent / '.env'
            decoy.write_text('RMFYALK_TOKEN=synthetic-decoy\nEXPORT_DIR=decoy-export\n')
            decoy.chmod(0o600)
            private = root / 'private/case-access.env'
            opens = []
            original = os.open
            def checked_open(path, *args, **kwargs):
                opens.append(Path(path))
                return original(path, *args, **kwargs)
            with patch.object(api, 'CASE_SCRIPTS', scripts), patch.object(api, 'access_path', return_value=private), \
                    patch.object(os, 'open', side_effect=checked_open), patch.dict(os.environ, {}, clear=True):
                client = api.load_client()
                self.assertEqual(client.DEFAULT_CREDENTIAL_PATH, private)
                self.assertEqual(client.client.credential_path, private)
                self.assertEqual(client.DEFAULT_EXPORT_DIR, '')
            self.assertEqual(opens, [private])

    def test_case_windows_reader_uses_safe_fd_and_preserves_bounds(self):
        self.assertTrue((ROOT / 'windows_case_access.py').is_file(), 'case adapter missing')
        import windows_case_access as api
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'synthetic.env'
            with patch.object(api, 'access_path', return_value=path):
                module = api.load_client()
            path.write_text('RMFYALK_TOKEN=synthetic-A\n')
            with patch.object(module, '_WINDOWS', True), \
                    patch('windows_private.open_file', side_effect=lambda p, **kw: os.open(p, os.O_RDONLY)) as opener:
                self.assertEqual(module.RmfyalkClient(path).token, 'synthetic-A')
                opener.assert_called_once_with(path, private=True)
                path.write_bytes(b'a' * (module.MAX_CREDENTIAL_BYTES + 1))
                with self.assertRaises(module.CredentialError) as raised:
                    module._read_bindings(path)
                self.assertEqual(raised.exception.kind, 'oversize')
            with patch.object(module, '_WINDOWS', True), \
                    patch('windows_private.open_file', side_effect=ValueError('unsafe synthetic')):
                with self.assertRaises(module.CredentialError) as raised:
                    module._read_bindings(path)
                self.assertEqual(raised.exception.kind, 'unsafe')
            with patch.object(module, '_WINDOWS', True), \
                    patch('windows_private.open_file', side_effect=RuntimeError('synthetic native access refusal')):
                with self.assertRaises(module.CredentialError) as raised:
                    module._read_bindings(path)
                self.assertEqual(raised.exception.kind, 'unreadable')

    def test_case_save_hidden_value_preserves_old_file_on_replace_failure(self):
        import windows_case_access as api
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / 'case-access.env'
            dest.write_text('old')
            dest.chmod(0o600)
            def safe_open(path, **kw):
                return os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600) if kw.get('exclusive') else os.open(path, os.O_RDONLY)
            with patch.object(api, 'access_path', return_value=dest), \
                    patch('windows_private.private_directory'), \
                    patch('windows_private.open_file', side_effect=safe_open), \
                    patch.object(api.os, 'replace', side_effect=OSError('failure')):
                with self.assertRaises(OSError):
                    api.save_local('synthetic-new')
            self.assertEqual(dest.read_text(), 'old')
            self.assertEqual(list(dest.parent.iterdir()), [dest])

    def test_installer_exposes_component_status_separately(self):
        source = (ROOT / 'scripts/install_windows.py').read_text()
        self.assertIn("state['external'] = install_components(bundle, target)", source)
        self.assertIn("completion_scope='core_only_external_status_separate'", source)

    def test_doctor_missing_components_and_host_conflict_are_distinct(self):
        api = self.api()
        self.assertTrue(hasattr(api, 'doctor'), 'External diagnostic entry missing')
        with tempfile.TemporaryDirectory() as folder:
            report = api.doctor(Path(folder))
            self.assertEqual(report['mcp1']['status'], 'missing')
            self.assertEqual(report['bb_browser']['status'], 'missing')
            self.assertEqual(report['case']['status'], 'pending_local_login_and_auth_search_body')
            self.assertFalse(report['ready_external'])

    def test_installer_stage_failure_does_not_leak_subprocess_output(self):
        api = self.api()
        self.assertTrue(hasattr(api, 'step'), 'Component stage reporting missing')
        def failing():
            raise subprocess.CalledProcessError(1, ['synthetic'], stderr='synthetic-secret')
        with self.assertRaises(Exception) as error:
            api.step('mcp1.import', failing)
        self.assertIn('mcp1.import', str(error.exception))
        self.assertNotIn('synthetic-secret', str(error.exception))

    def test_browser_install_freezes_dependencies_then_applies_verified_copy(self):
        api = self.api()
        import windows_browser
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)
            vendor = target / 'vendor/bb-browser'
            shutil.copytree(ROOT / 'vendor/bb-browser/package', vendor / 'package')
            calls = []
            def run(command, **kwargs):
                command = [str(x) for x in command]
                calls.append((command, kwargs))
                if 'install' in command:
                    installed = vendor / 'node_modules/bb-browser/dist'
                    installed.mkdir(parents=True)
                    shutil.copyfile(ROOT / 'vendor/bb-browser/provenance/cli.original.js', installed / 'cli.js')
                    shutil.copyfile(ROOT / 'vendor/bb-browser/provenance/daemon.input.js', installed / 'daemon.js')
                    text = ''
                elif len(command) == 2:
                    text = 'v22.23.3'
                elif command[1].endswith('pnpm.cjs'):
                    text = '11.25.0'
                else:
                    text = '0.14.2'
                return subprocess.CompletedProcess(command, 0, text, '')
            with patch('scripts.install_windows.extract_runtime'), patch.object(api, 'extract_pnpm'), \
                    patch.object(api.subprocess, 'run', side_effect=run):
                result = api.install_browser(target / 'bundle', target)
            self.assertEqual(result['status'], 'installed_native_pending')
            install = next(command for command, _ in calls if 'install' in command)
            self.assertEqual(install[-4:], ['install', '--frozen-lockfile', '--ignore-scripts', '--prod'])
            self.assertTrue(all(command[0] == str(windows_browser.node_path(target)) for command, _ in calls))
            windows_browser.verify_payload(target)


class BrowserTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('windows_browser'), 'browser adapter missing')
        import windows_browser
        return windows_browser

    def test_only_single_help_version_exempt_and_no_redirect_flags(self):
        api = self.api()
        for flag in ['--help', '-h', '--version', '-v']:
            self.assertTrue(api.offline_args([flag]))
            self.assertFalse(api.offline_args([flag, 'daemon', 'start']))
        for args in [['daemon'], ['daemon', 'stop'], ['--hub=x'], ['--cdp-port', '9222']]:
            with self.assertRaises(ValueError):
                api.validate_args(args)

    def test_fixed_environment_clears_hub_and_runtime_injection(self):
        api = self.api()
        with patch.dict(os.environ, {'BB_BROWSER_HUB_TOKEN': 'private', 'PINIX_TOKEN': 'private',
                                   'BB_BROWSER_CDP_URL': 'http://foreign', 'NODE_OPTIONS': '--bad'}):
            env = api.browser_env(ROOT)
        self.assertEqual(env['BB_BROWSER_CDP_URL'], 'http://127.0.0.1:19224')
        self.assertFalse(any('HUB' in key or key == 'PINIX_TOKEN' for key in env))
        self.assertNotIn('NODE_OPTIONS', env)

    def test_unknown_daemon_and_occupied_browser_port_refused(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state = root / 'private/bb-state'
            state.mkdir(parents=True)
            (state / 'daemon.json').write_text('{"pid":123}')
            with self.assertRaisesRegex(ValueError, 'daemon'):
                api.check_daemon(root)
            with patch('scripts.install_windows.port_free', return_value=False):
                with self.assertRaisesRegex(ValueError, '19224'):
                    api.start_browser(root)

    def test_disconnected_browser_prevents_cli(self):
        api = self.api()
        with patch.object(api, 'verify_payload'), patch.object(api, 'check_browser', side_effect=ValueError('disconnected')), \
                patch.object(api.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'disconnected'):
                api.invoke(ROOT, ['get', 'title'])
            run.assert_not_called()

    def test_payload_patch_identity_is_enforced(self):
        api = self.api()
        source = ROOT / 'vendor/bb-browser/package'
        self.assertTrue(source.is_dir(), 'vendored browser missing')
        api.verify_source(source)
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder)
            (dest / 'dist').mkdir()
            (dest / 'dist/cli.js').write_text('wrong')
            with self.assertRaises(ValueError):
                api.verify_source(dest)

    def test_foreign_or_reused_pid_is_rejected_before_network(self):
        api = self.api()
        owner = {'pid': 5, 'exe': 'signed-browser.exe', 'command': 'dedicated-profile', 'created': 'old'}
        actual = {**owner, 'created': 'reused', 'listeners': [{'address': '127.0.0.1', 'port': 19224}]}
        with self.assertRaisesRegex(ValueError, 'identity'):
            api.same_process(owner, actual, 19224)
        with self.assertRaisesRegex(ValueError, 'ownership'):
            api.same_process(owner, owner, 19224)

    def test_unknown_service_on_daemon_port_is_refused(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(api, 'verify_payload'), patch.object(api, 'check_browser'), \
                patch('scripts.install_windows.port_free', return_value=False), \
                patch.object(api.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, '19824'):
                api.invoke(Path(folder), ['get', 'title'])
            run.assert_not_called()

    def test_unverified_browser_never_launches(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)
            candidate = target / 'chrome.exe'
            candidate.write_bytes(b'synthetic')
            with patch('scripts.install_windows.port_free', return_value=True), \
                    patch.object(api, 'powershell', return_value={'status': 'NotSigned'}), \
                    patch.object(api.subprocess, 'Popen') as launch:
                with self.assertRaisesRegex(ValueError, 'pending'):
                    api.start_browser(target, candidate)
                launch.assert_not_called()
            self.assertFalse((target / 'private').exists())

    def test_openclaw_and_unmigrated_routes_stop_before_any_browser_or_process(self):
        api = self.api()
        refused = [
            ['site', 'example/demo', '--openclaw'], ['--openclaw', 'tab', 'list'],
            ['site', '--openclaw', 'run', 'example/demo'], ['--openclaw=true', 'site', 'list'],
            ['site', 'recommend'], ['--json', 'site', 'recommend'],
            ['site', '--json', 'recommend'], ['--days', '3', 'site', 'recommend'],
            ['--jq', '.', 'site', '--days', '3', 'recommend'],
            ['site', 'update'], ['--json', 'site', 'update'],
            ['--tab', 'site', 'site', 'update'], ['site', '--filter', 'unused', 'update'],
        ]
        for args in refused:
            with self.subTest(args=args), patch.object(api, 'verify_payload') as verify, \
                    patch.object(api, 'check_browser') as browser, \
                    patch.object(api.subprocess, 'run') as run:
                with self.assertRaises(ValueError):
                    api.invoke(ROOT, args)
                verify.assert_not_called()
                browser.assert_not_called()
                run.assert_not_called()

    def test_normal_site_and_core_commands_remain_available(self):
        api = self.api()
        allowed = [['tab', 'list'], ['get', 'title', '--tab', '07'],
                   ['eval', 'document.title', '--tab', '07'],
                   ['--json', 'site', 'list'], ['site', 'info', 'example/demo'],
                   ['site', 'search', 'update'], ['site', 'run', 'example/demo'],
                   ['site', 'example/demo'], ['--jq', 'recommend', 'site', 'search', 'update']]
        for args in allowed:
            with self.subTest(args=args):
                api.validate_args(args)

    def test_cli_call_is_bounded_and_timeout_reports_no_captured_output(self):
        api = self.api()
        with patch.object(api, 'verify_payload'), \
                patch.object(api, 'check_browser'), patch.object(api, 'check_daemon', return_value={'pid': 5}), \
                patch.object(api.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertEqual(api.invoke(ROOT, ['get', 'title', '--tab', '07']), 0)
            self.assertEqual(run.call_args.kwargs.get('timeout'), 120)
        failure = subprocess.TimeoutExpired(['synthetic-secret-argument'], 120,
                                            output='synthetic-secret-output', stderr='synthetic-secret-error')
        with patch.object(api, 'verify_payload'), patch.object(api, 'remember_daemon') as remember, \
                patch.object(api.subprocess, 'run', side_effect=failure):
            with self.assertRaisesRegex(ValueError, 'timed out') as error:
                api.invoke(ROOT, ['--version'])
            self.assertNotIn('synthetic-secret', str(error.exception))
            remember.assert_not_called()


@unittest.skipUnless(os.name == 'nt', 'PENDING: native Windows case ACL integration')
class WindowsCaseNativeTests(unittest.TestCase):
    def test_private_save_read_refresh_and_bounded_file(self):
        import windows_case_access as api
        import windows_private
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'private/case-access.env'
            with patch.object(api, 'access_path', return_value=path):
                api.save_local('synthetic-A')
                client = api.load_client().client
                self.assertEqual(client.token, 'synthetic-A')
                api.save_local('synthetic-B')
                self.assertEqual(client.token, 'synthetic-B')
                with os.fdopen(windows_private.open_file(path, private=True, writable=True), 'wb') as output:
                    output.write(b'x' * 65537)
                with self.assertRaises(Exception):
                    client.token

    def test_broad_existing_file_rejected(self):
        import windows_case_access as api
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'public.env'
            path.write_text('RMFYALK_TOKEN=synthetic-A')
            with patch.object(api, 'access_path', return_value=Path(folder) / 'missing.env'):
                module = api.load_client()
            # Grant Everyone read explicitly so this doesn't depend on temp ACL defaults.
            import win32security as security
            acl = security.ACL()
            acl.AddAccessAllowedAce(security.ACL_REVISION, 0x120089, security.CreateWellKnownSid(security.WinWorldSid, None))
            security.SetNamedSecurityInfo(str(path), security.SE_FILE_OBJECT,
                security.DACL_SECURITY_INFORMATION | security.PROTECTED_DACL_SECURITY_INFORMATION, None, None, acl, None)
            with self.assertRaises(module.CredentialError) as raised:
                module._read_bindings(path)
            self.assertEqual(raised.exception.kind, 'unsafe')


if __name__ == '__main__':
    unittest.main()
