"""Core Windows installer contracts; OS actions are fakes, never native evidence."""
import hashlib
import errno
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile


class WindowsInstallTests(unittest.TestCase):
    def partial_write_failure(self, writes):
        original_open = io.open
        def open_with_failure(file, mode='r', *args, **kwargs):
            stream = original_open(file, mode, *args, **kwargs)
            if 'w' in mode:
                original_write = stream.write
                def interrupted_write(content):
                    original_write(content[:2])
                    stream.flush()
                    writes.append(stream.name)
                    raise OSError(errno.ENOSPC, 'simulated full disk after partial write')
                stream.write = interrupted_write
            return stream
        return patch.object(io, 'open', side_effect=open_with_failure)

    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('scripts.install_windows'),
                             'Windows installer must exist')
        from scripts import install_windows
        return install_windows

    def bundle(self, root):
        files = {'source/legal_mcp.py': b'# source',
                 'source/requirements-windows.lock.txt': b'# locked',
                 'source/scripts/install_windows.py': b'# installer',
                 'data/personal-public-library.zip': b'fake archive',
                 'runtime/python-3.13.16-amd64.zip': b'fake python',
                 'runtime/wheels-main/example.whl': b'wheel',
                 'skills/cn-litigation-redteam/SKILL.md': b'# skill',
                 'windows_bootstrap.ps1': b'# bootstrap', 'install.cmd': b'@echo off'}
        for name, raw in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        manifest = {'schema_version': 1, 'files': {name: {
            'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
            for name, raw in files.items()}}
        (root / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        return manifest

    def test_bundle_integrity_rejects_mutation_missing_extra_and_symlink(self):
        api = self.api()
        for failure in ('hash', 'missing', 'extra', 'symlink', 'size'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                expected = self.bundle(root)
                self.assertEqual(api.verify_bundle(root), expected)
                path = root / 'source/legal_mcp.py'
                if failure == 'hash':
                    path.write_bytes(b'# sourcE')
                elif failure == 'size':
                    path.write_bytes(b'longer content')
                elif failure == 'extra':
                    (root / 'unknown.txt').write_text('extra')
                else:
                    path.unlink()
                    if failure == 'symlink':
                        path.symlink_to(root / 'source/requirements-windows.lock.txt')
                with self.assertRaises(ValueError):
                    api.verify_bundle(root)

    def test_bundle_rejects_unsafe_names_and_case_directory_aliases(self):
        api = self.api()
        for name in ('source/../escape.py', 'source/CON.py', 'source/a:stream.py',
                     'source/scripts/a. ', 'source/config/local-machine.json',
                     'source/__pycache__/a.pyc', 'vendor/treasury/.env', 'other/a.txt'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                api.allowed_payload(name)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self.bundle(root)
            doc = json.loads((root / 'manifest.json').read_text())
            doc['files']['source/Scripts/extra.py'] = {'size': 0, 'sha256': '0' * 64}
            (root / 'manifest.json').write_text(json.dumps(doc))
            with self.assertRaises(ValueError):
                api.verify_bundle(root)

    def test_host_rejects_non_windows_wrong_arch_and_build_before_writes(self):
        api = self.api()
        for system, machine, build in [('Darwin', 'arm64', 19045),
                                      ('Windows', 'ARM64', 19045),
                                      ('Windows', 'AMD64', 22000),
                                      ('Windows', 'AMD64', 17000)]:
            with self.subTest(system=system, machine=machine, build=build), \
                    patch.object(api.platform, 'system', return_value=system), \
                    patch.object(api.platform, 'machine', return_value=machine), \
                    patch.object(api.sys, 'getwindowsversion', create=True,
                        return_value=SimpleNamespace(major=10, build=build, product_type=1)), \
                    self.assertRaises(ValueError):
                api.check_host()

    def test_runtime_requires_actual_imports_timezone_utf8_and_fts(self):
        api = self.api()
        report = dict(system='Windows', machine='AMD64', version=[3, 13, 16],
                      bits=64, fts5_trigram=True, utf8=True, timezone=True,
                      dependencies={'mcp': True, 'yaml': True})
        api.validate_runtime(report)
        for key in ('fts5_trigram', 'utf8', 'timezone'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                api.validate_runtime({**report, key: False})

    def test_existing_target_and_failed_manifest_never_restore(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as tmp, patch.object(api, 'check_host'), \
                patch.object(api, 'restore_library') as restore:
            root = Path(tmp).resolve()
            bundle = root / 'bundle'
            self.bundle(bundle)
            target = root / 'existing'
            target.mkdir()
            with self.assertRaises(FileExistsError):
                api.install(bundle, target)
            (bundle / 'source/legal_mcp.py').write_bytes(b'corrupt')
            with self.assertRaises(ValueError):
                api.install(bundle, root / 'new')
            restore.assert_not_called()

    def test_final_runtime_is_used_and_dependency_failure_retains_failed_target(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            bundle, target = base / 'bundle', base / '目标 空间'
            self.bundle(bundle)
            calls = []
            def restore(archive, destination):
                (destination / 'config').mkdir(parents=True)
                (destination / 'config/shared-library.json').write_text('{"relocated":true}')
            def extract(archive, destination, **kwargs):
                destination.mkdir(parents=True)
                (destination / 'python.exe').write_bytes(b'python')
            def run(command, **kwargs):
                calls.append([str(item) for item in command])
                if 'pip' in command:
                    raise subprocess.CalledProcessError(1, command, stderr='offline wheel missing')
                return SimpleNamespace(stdout='{}', returncode=0)
            with patch.object(api, 'check_host', return_value={'build': 19045}), patch.object(api, 'restore_library', side_effect=restore), \
                    patch.object(api, 'extract_runtime', side_effect=extract), \
                    patch.object(api, 'run', side_effect=run):
                with self.assertRaises(subprocess.CalledProcessError):
                    api.install(bundle, target)
            state = json.loads((target / 'verification/install/state.json').read_text())
            self.assertEqual(state['status'], 'failed')
            self.assertFalse(state['activated'])
            self.assertEqual(calls[0][0], str(target / 'runtime/python/python.exe'))
            self.assertIn(str(target / '.venv'), calls[0])
            self.assertIn('--require-hashes', calls[1])
            self.assertIn('--no-index', calls[1])
            self.assertEqual((target / 'config/shared-library.json').read_text(), '{"relocated":true}')
            self.assertTrue((target / 'skills/cn-litigation-redteam/SKILL.md').exists())

    def test_runtime_extraction_rejects_wrong_hash_traversal_and_links(self):
        api = self.api()
        for name, mode in [('../escape', 0), ('CON.txt', 0), ('python.exe', 0o120777 << 16)]:
            with tempfile.TemporaryDirectory() as tmp:
                archive = Path(tmp) / 'runtime.zip'
                with zipfile.ZipFile(archive, 'w') as out:
                    info = zipfile.ZipInfo(name)
                    info.external_attr = mode
                    out.writestr(info, b'runtime')
                digest = hashlib.sha256(archive.read_bytes()).hexdigest()
                with self.assertRaises(ValueError):
                    api.extract_runtime(archive, Path(tmp) / 'runtime', expected_hash=digest)
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / 'runtime.zip'
            archive.write_bytes(b'wrong')
            with self.assertRaises(ValueError):
                api.extract_runtime(archive, Path(tmp) / 'runtime')

    def test_run_uses_list_timeout_and_utf8_without_pythonpath(self):
        api = self.api()
        with patch.dict(os.environ, {'PYTHONPATH': 'bad', 'PYTHONHOME': 'bad'}), \
                patch.object(api.subprocess, 'run') as process:
            api.run([Path('目标 空间/python.exe'), '-X', 'utf8'], timeout=12)
        args, kwargs = process.call_args
        self.assertIsInstance(args[0], list)
        self.assertEqual(kwargs['timeout'], 12)
        self.assertNotIn('PYTHONPATH', kwargs['env'])
        self.assertEqual(kwargs['env']['PYTHONUTF8'], '1')
        self.assertFalse(kwargs.get('shell', False))

    def test_doctor_does_not_claim_unchecked_optional_features(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as tmp, patch.object(api, 'probe_runtime',
                side_effect=FileNotFoundError('python missing')), patch.object(api, 'port_free', return_value=True):
            report = api.doctor(Path(tmp))
        for key in ('ready_search', 'ready_pdf', 'ready_doc', 'ready_update', 'ready_mock_hearing'):
            self.assertFalse(report[key])
        self.assertFalse(report['login_restart_verified'])
        self.assertEqual(report['browser'], 'pending_native_test')

    def test_activate_refuses_conflict_and_unhealthy_without_task_calls(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp).resolve()
            api.save_state(target, {'status': 'complete', 'target': str(target), 'install_id': 'x'})
            for available, healthy in [(False, True), (True, False)]:
                with patch.object(api, 'check_host'), patch.object(api, 'port_free', return_value=available), \
                        patch.object(api, 'doctor', return_value={'ready_search': healthy}), \
                        patch.object(api, 'task_action') as tasks, self.assertRaises(ValueError):
                    api.activate(target)
                tasks.assert_not_called()

    def test_task_manifest_quotes_paths_and_deactivate_preserves_data(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp).resolve() / '目标 空间'
            target.mkdir()
            evidence = target / 'evidence.txt'
            evidence.write_text('retained')
            api.save_state(target, {'status': 'complete', 'target': str(target), 'install_id': 'test-id'})
            manifest = api.task_manifest(target, 'test-id')
            self.assertIn('"', manifest['tasks'][0]['arguments'])
            self.assertEqual(manifest['tasks'][0]['execute'], str(target / '.venv/Scripts/python.exe'))
            with patch.object(api, 'check_host'), patch.object(api, 'task_action', return_value={'disabled': True}):
                api.deactivate(target)
            self.assertEqual(evidence.read_text(), 'retained')
            self.assertFalse(json.loads((target / 'verification/install/state.json').read_text())['activated'])

    def test_bootstrap_verifies_before_execution_and_no_global_policy(self):
        api = self.api()
        bootstrap = (api.ROOT / 'scripts/windows_bootstrap.ps1').read_text()
        tasks = (api.ROOT / 'scripts/windows_tasks.ps1').read_text()
        self.assertIn(api.PYTHON_SHA256, bootstrap)
        self.assertLess(bootstrap.index('Get-FileHash'), bootstrap.index('& $python'))
        self.assertIn('TASK_CREATE', tasks)
        self.assertNotIn('Set-ExecutionPolicy', bootstrap + tasks)
        self.assertIn('InteractiveToken', tasks)
        self.assertIn('StartWhenAvailable', tasks)
        self.assertIn('Assert-Owned', tasks)
        self.assertIn('InnerException', tasks)

    def test_bootstrap_requires_clear_activation_choice_or_explicit_switch(self):
        api = self.api()
        script = (api.ROOT / 'scripts/windows_bootstrap.ps1').read_text()
        self.assertIn('[switch]$Activate', script)
        self.assertIn('if ($Activate -and $NoActivate)', script)
        self.assertIn('if (-not $Activate -and -not $NoActivate)', script)
        self.assertIn('current user signs in', script)
        self.assertIn('every 5 minutes', script)
        self.assertIn('No Windows password is stored', script)
        consent = script.index("Read-Host 'Enable these tasks? [Y/n]'")
        self.assertLess(consent, script.index('& $python'))
        self.assertIn("if ($enableTasks) { $arguments += '--activate' }", script)
        self.assertNotIn("if (-not $NoActivate) { $arguments += '--activate' }", script)

    def test_task_registration_failure_is_recorded_without_claiming_activation(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp).resolve()
            api.save_state(target, {'status': 'complete', 'target': str(target),
                                   'install_id': 'test-id', 'activated': False})
            error = subprocess.CalledProcessError(1, ['powershell'], stderr='Task exists; not overwritten')
            with patch.object(api, 'check_host'), patch.object(api, 'port_free', return_value=True), \
                    patch.object(api, 'doctor', return_value={'ready_search': True}), \
                    patch.object(api, 'task_action', side_effect=error), \
                    self.assertRaises(subprocess.CalledProcessError):
                api.activate(target)
            state = json.loads((target / 'verification/install/state.json').read_text())
            self.assertEqual(state['status'], 'complete')
            self.assertEqual(state['autostart'], 'activation_failed_review_required')
            self.assertIn('Task exists', state['activation_error'])
            self.assertFalse(state['activated'])

    def test_state_write_failure_removes_new_tasks_but_only_disables_resumed_tasks(self):
        api = self.api()
        for activation_mode, rollback in [('created', 'Remove'), ('resumed', 'Disable')]:
            with self.subTest(mode=activation_mode), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp).resolve()
                api.save_state(target, {'status': 'complete', 'target': str(target),
                                       'install_id': 'test-id', 'activated': False})
                with patch.object(api, 'check_host'), patch.object(api, 'port_free', return_value=True), \
                        patch.object(api, 'doctor', return_value={'ready_search': True}), \
                        patch.object(api, 'task_action', return_value={
                            'activated': True, 'activation_mode': activation_mode}) as tasks, \
                        patch.object(api, 'save_state', side_effect=OSError('state write failed')), \
                        self.assertRaisesRegex(OSError, 'state write failed'):
                    api.activate(target)
                self.assertEqual([call.args[1] for call in tasks.call_args_list], ['Activate', rollback])

    def test_partial_state_write_retains_old_bytes_and_only_cleans_own_temp(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp).resolve()
            api.save_state(target, {'status': 'complete', 'install_id': 'old-identity'})
            path = target / 'verification/install/state.json'
            before = path.read_bytes()
            sentinel = path.with_name('.state-unrelated.tmp')
            sentinel.write_text('not owned by this save')
            writes = []
            with self.partial_write_failure(writes), self.assertRaises(OSError) as failure:
                api.save_state(target, {'status': 'complete', 'install_id': 'new-identity'})
            self.assertEqual(failure.exception.errno, errno.ENOSPC)
            self.assertEqual(len(writes), 1, 'Fault must follow an actual partial write')
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(sentinel.read_text(), 'not owned by this save')
            self.assertEqual(set(path.parent.iterdir()), {path, sentinel})

    def test_state_replace_failure_preserves_old_identity_and_removes_temp(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp).resolve()
            api.save_state(target, {'status': 'complete', 'install_id': 'old-identity'})
            path = target / 'verification/install/state.json'
            before = path.read_bytes()
            def fail_replace(source, destination):
                self.assertEqual(Path(source).parent, path.parent)
                self.assertNotEqual(Path(source), path)
                self.assertEqual(Path(destination), path)
                self.assertEqual(json.loads(Path(source).read_text())['install_id'], 'new-identity')
                raise OSError(errno.EACCES, 'simulated replace refusal')
            with patch.object(api.os, 'replace', side_effect=fail_replace), self.assertRaises(OSError):
                api.save_state(target, {'status': 'complete', 'install_id': 'new-identity'})
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_partial_write_during_activation_preserves_identity_for_both_rollbacks(self):
        api = self.api()
        for mode, rollback in [('created', 'Remove'), ('resumed', 'Disable')]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp).resolve()
                state = {'status': 'complete', 'target': str(target),
                         'install_id': 'test-id', 'activated': False}
                api.save_state(target, state)
                path = target / 'verification/install/state.json'
                before = path.read_bytes()
                actions, writes = [], []
                def tasks(destination, action, install_id):
                    # Same identity parsing requirement as the PowerShell preflight.
                    self.assertEqual(api.installed_state(destination), state)
                    self.assertEqual(install_id, state['install_id'])
                    actions.append(action)
                    return {'activated': True, 'activation_mode': mode}
                with patch.object(api, 'check_host'), patch.object(api, 'port_free', return_value=True), \
                        patch.object(api, 'doctor', return_value={'ready_search': True}), \
                        patch.object(api, 'task_action', side_effect=tasks), \
                        self.partial_write_failure(writes), self.assertRaises(OSError) as failure:
                    api.activate(target)
                self.assertEqual(failure.exception.errno, errno.ENOSPC)
                self.assertEqual(len(writes), 1)
                self.assertEqual(actions, ['Activate', rollback])
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(list(path.parent.iterdir()), [path])

    def test_resume_branch_preflights_all_tasks_and_never_registers_or_deletes(self):
        api = self.api()
        script = (api.ROOT / 'scripts/windows_tasks.ps1').read_text()
        self.assertIn('$existing.Count -ne 0 -and $existing.Count -ne 2', script)
        self.assertIn('if ($task.Enabled)', script)
        self.assertIn('if ($existing.Count -eq 2)', script)
        branch = script.split('if ($existing.Count -eq 2)', 1)[1].split('$created = @()', 1)[0]
        self.assertNotIn('RegisterTaskDefinition', branch)
        self.assertNotIn('DeleteTask', branch)
        self.assertLess(script.index('if ($task.Enabled)'), script.index('$task.Enabled = $true'))
        self.assertIn('$enabled += $spec', branch)
        self.assertIn('$task.Enabled = $false', branch)
        self.assertIn("activation_mode='resumed'", branch)
        self.assertIn("activation_mode='created'", script)

    def test_successful_install_creates_config_fragment_without_host_edits(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            bundle, target = base / 'bundle', base / '目标 空间'
            self.bundle(bundle)
            def restore(archive, destination):
                (destination / 'config').mkdir(parents=True)
            report = {'ready_search': True, 'ready_pdf': True, 'ready_mock_hearing': True,
                      'ready_update': False, 'ready_doc': False}
            with patch.object(api, 'check_host', return_value={'build': 19045}), \
                    patch.object(api, 'restore_library', side_effect=restore), \
                    patch.object(api, 'extract_runtime'), patch.object(api, 'run'), \
                    patch.object(api, 'doctor', return_value=report):
                state = api.install(bundle, target)
            self.assertEqual(state['status'], 'complete')
            self.assertFalse(state['activated'])
            self.assertEqual(state['skills'], 'bundled_not_imported_into_host')
            import tomllib
            fragment = tomllib.loads((target / 'verification/install/codex-mcp.toml').read_text())
            connection = fragment['mcp_servers']['chiheng_legal']
            self.assertEqual(connection['command'], str(target / '.venv/Scripts/python.exe'))
            self.assertEqual(connection['args'][-1], str(target / 'legal_mcp.py'))

    def test_smoke_checks_relocated_synthetic_library_and_rejects_changed_raw(self):
        api = self.api()
        from legal_store import LegalStore
        from library_transfer import export_library, restore_library
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            source, target = base / 'source', base / '移植 目录'
            (source / 'config').mkdir(parents=True)
            (source / 'verification').mkdir()
            store = LegalStore(source / 'data/legal.sqlite3')
            store.add(law_id='synthetic', title='合成验证法规', text='第一条 合成公开正文内容。',
                      source_url='https://example.org/synthetic', locator='第一条', region='CN')
            store.close()
            corpus = source / 'corpus.json'
            corpus.write_text(json.dumps({'laws': {'synthetic': {'title': '合成验证法规',
                'urls': ['https://example.org/synthetic'], 'provisions': [
                    {'article': '第一条', 'text': '第一条 合成公开正文内容。'}]}}}), encoding='utf-8')
            (source / 'config/shared-library.json').write_text(json.dumps({
                'corpus_path': str(corpus), 'library_id': 'synthetic', 'purpose': 'test',
                'offline_review_state': 'unverified_mirror'}), encoding='utf-8')
            raw = source / 'data/quarantine/original.html'
            raw.parent.mkdir()
            raw.write_text('<p>合成公开正文内容。</p>', encoding='utf-8')
            archive = base / 'library.zip'
            export_library(source, archive)
            restore_library(archive, target)
            for path in api.ROOT.glob('*.py'):
                shutil.copyfile(path, target / path.name)
            result = api.run([sys.executable, '-X', 'utf8', '-c', api.SMOKE], cwd=target)
            report = json.loads(result.stdout)
            self.assertTrue(report['source_card'])
            self.assertTrue(report['fragment'])
            self.assertTrue(report['mirror'])
            (target / report['raw_file']).write_bytes(b'tampered')
            with self.assertRaises(subprocess.CalledProcessError):
                api.run([sys.executable, '-X', 'utf8', '-c', api.SMOKE], cwd=target)

    def test_missing_runtime_and_diagnostic_stderr_are_preserved(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp).resolve()
            with self.assertRaises(FileNotFoundError):
                api.probe_runtime(target / 'python.exe')
            error = subprocess.CalledProcessError(1, ['pip'], stderr='missing locked wheel')
            self.assertIn('missing locked wheel', api.error_detail(error))

    def test_pdf_probe_extracts_known_text_with_both_engines(self):
        api = self.api()
        result = api.run([sys.executable, '-X', 'utf8', '-c',
                         "import sys; sys.modules['reportlab'] = None\n" + api.PDF_PROBE])
        self.assertEqual(json.loads(result.stdout), {'pypdf_text': 'Chiheng PDF probe',
                                                   'pdfplumber_text': 'Chiheng PDF probe'})

    def test_task_execution_uses_bounded_update_and_streams_logs(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'task.log'
            with patch.object(api.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as process:
                api.run(['python.exe', 'script.py'], timeout=3600, log=log)
            self.assertEqual(process.call_args.kwargs['timeout'], 3600)
            self.assertEqual(process.call_args.kwargs['stderr'], subprocess.STDOUT)
            self.assertNotIn('capture_output', process.call_args.kwargs)

    def test_source_copy_rejects_changed_bytes_and_never_overwrites(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp).resolve() / 'bundle'
            manifest = self.bundle(bundle)
            target = Path(tmp).resolve() / 'target'
            target.mkdir()
            (bundle / 'source/legal_mcp.py').write_bytes(b'changed')
            with self.assertRaises(ValueError):
                api.copy_payload(bundle, target, manifest)
            before = (target / 'legal_mcp.py').read_bytes()
            with self.assertRaises(FileExistsError):
                api.copy_payload(bundle, target, manifest)
            self.assertEqual((target / 'legal_mcp.py').read_bytes(), before)


class WindowsConverterTests(unittest.TestCase):
    def test_soffice_program_files_windows(self):
        import local_settings as settings
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / 'LibreOffice/program/soffice.exe'
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b'exe')
            exe.chmod(0o700)
            with patch.object(settings.sys, 'platform', 'win32'), \
                    patch.dict(os.environ, {'ProgramFiles': tmp}, clear=True), \
                    patch.object(settings, 'configured_path', return_value=None), \
                    patch.object(settings.shutil, 'which', return_value=None):
                self.assertEqual(settings.resolve_soffice(), exe)

    def test_catalog_uses_existing_windows_system_curl(self):
        from scripts import refresh_upstream_catalog as catalog
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / 'System32/curl.exe'
            exe.parent.mkdir()
            exe.write_bytes(b'exe')
            with patch.object(catalog.sys, 'platform', 'win32'), \
                    patch.dict(os.environ, {'SystemRoot': tmp}), \
                    patch.object(catalog.subprocess, 'run', return_value=SimpleNamespace(stdout=b'{}')) as process:
                catalog.fetch_json('https://api.github.com/test')
            self.assertEqual(process.call_args.args[0][0], str(exe))
            self.assertNotIn('--insecure', process.call_args.args[0])


@unittest.skipUnless(os.name == 'nt', 'PENDING: PowerShell 5.1 interpreter with fake scheduler objects')
class WindowsTaskResumeInterpreterTests(unittest.TestCase):
    def test_resume_matrix_with_fake_scheduler_and_no_system_task_changes(self):
        """Execute production control flow; replace only COM setup and the port probe."""
        from scripts import install_windows as api
        source = (api.ROOT / 'scripts/windows_tasks.ps1').read_text()
        body = source[source.index('function Find-Task'):]
        port_probe = ("$listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 18063)\n"
                      "try { $listener.Start() } finally { $listener.Stop() }")
        self.assertEqual(body.count(port_probe), 1)
        body = body.replace(port_probe, '# Port probe isolated; Python port-conflict test covers refusal.')
        harness = r'''
param([string]$Case, [string]$Body, [string]$Snapshot)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$target = 'C:\Synthetic Target'
$sid = 'S-1-5-21-synthetic'
$marker = 'synthetic installation'
$Mode = if ($Case -eq 'disable') { 'Disable' } else { 'Activate' }
$request = @{ tasks=@() }
$script:tasks = @{}
$script:events = [Collections.Generic.List[string]]::new()
foreach ($kind in @('mcp','update')) {
    $spec = [pscustomobject]@{ name=('Chiheng-1234567890abcdef-' + $kind); kind=$kind;
        execute=(Join-Path $target '.venv\Scripts\python.exe'); arguments=('synthetic ' + $kind);
        working_directory=$target }
    $request.tasks += $spec
    $actions = [pscustomobject]@{ Count=1; Action=[pscustomobject]@{ Type=0;
        Path=$spec.execute; Arguments=$spec.arguments; WorkingDirectory=$target } }
    $actions | Add-Member ScriptMethod Item { param($index) return $this.Action }
    $task = [pscustomobject]@{ Name=$spec.name; Flag=($Case -eq 'disable');
        FailEnable=($Case -eq 'enable_failure' -and $kind -eq 'update');
        FailRun=($Case -eq 'run_failure' -and $kind -eq 'mcp');
        Definition=[pscustomobject]@{ RegistrationInfo=[pscustomobject]@{ Description=$marker };
            Principal=[pscustomobject]@{ UserId=$sid; LogonType=3; RunLevel=0 }; Actions=$actions } }
    $task | Add-Member ScriptProperty Enabled { return $this.Flag } {
        param($value)
        $script:events.Add(('set:' + $this.Name + ':' + $value))
        if ($value -and $this.FailEnable) { throw 'simulated setter failure' }
        $this.Flag = $value
    }
    $task | Add-Member ScriptMethod Run {
        param($unused)
        $script:events.Add(('run:' + $this.Name))
        if ($this.FailRun) { throw 'simulated MCP start failure' }
    }
    $task | Add-Member ScriptMethod Stop { param($unused) $script:events.Add(('stop:' + $this.Name)) }
    $script:tasks[$spec.name] = $task
}
$first, $second = $request.tasks
switch ($Case) {
    'absent' { $script:tasks.Clear() }
    'partial' { $script:tasks.Remove($second.name) }
    'foreign' { $script:tasks[$second.name].Definition.RegistrationInfo.Description = 'foreign' }
    'principal' { $script:tasks[$second.name].Definition.Principal.UserId = 'another user' }
    'action' { $script:tasks[$second.name].Definition.Actions.Action.Arguments = 'changed' }
    'mixed' { $script:tasks[$second.name].Flag = $true }
    'enabled' { $script:tasks[$first.name].Flag = $true; $script:tasks[$second.name].Flag = $true }
}
$folder = [pscustomobject]@{}
$folder | Add-Member ScriptMethod GetTask {
    param($name)
    if (-not $script:tasks.ContainsKey($name)) { throw [IO.FileNotFoundException]::new('fake missing') }
    return $script:tasks[$name]
}
$folder | Add-Member ScriptMethod DeleteTask { param($name, $flags) throw 'Unexpected deletion' }
$folder | Add-Member ScriptMethod RegisterTaskDefinition { throw 'Unexpected registration' }
$service = [pscustomobject]@{}
$service | Add-Member ScriptMethod NewTask {
    param($flags)
    $script:events.Add('create-only-branch')
    throw 'First-creation branch reached (outside this restore test)'
}
try { . ([ScriptBlock]::Create((Get-Content -LiteralPath $Body -Raw -Encoding UTF8))) }
finally {
    $flags = @{}
    foreach ($name in $script:tasks.Keys) { $flags[$name] = $script:tasks[$name].Flag }
    @{ flags=$flags; events=@($script:events) } | ConvertTo-Json -Depth 8 |
        Set-Content -LiteralPath $Snapshot -Encoding UTF8
}
'''
        powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / 'harness.ps1').write_text(harness, encoding='utf-8')
            (base / 'body.ps1').write_text(body, encoding='utf-8')
            for case in ('disable', 'resume', 'absent', 'partial', 'foreign', 'principal',
                         'action', 'mixed', 'enabled', 'enable_failure', 'run_failure'):
                with self.subTest(case=case):
                    snapshot = base / (case + '.json')
                    result = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive',
                        '-ExecutionPolicy', 'Bypass', '-File', str(base / 'harness.ps1'), case,
                        str(base / 'body.ps1'), str(snapshot)], capture_output=True, timeout=30)
                    evidence = json.loads(snapshot.read_text(encoding='utf-8-sig'))
                    flags, events = evidence['flags'], evidence['events']
                    if case in ('resume', 'disable'):
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(list(flags.values()), [case == 'resume'] * 2)
                        if case == 'resume':
                            self.assertIn(b'"activation_mode":"resumed"', result.stdout)
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        if case == 'absent':
                            self.assertEqual(events, ['create-only-branch'])
                        elif case in ('enable_failure', 'run_failure'):
                            self.assertEqual(list(flags.values()), [False, False])
                            self.assertTrue(any(event.startswith('set:') for event in events))
                        else:
                            self.assertEqual(events, [], 'Preflight rejection changed another task')
