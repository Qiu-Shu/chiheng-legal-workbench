import importlib
from contextlib import closing
import json
import os
import plistlib
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from legal_store import LegalStore
from library_transfer import export_library


class MacInstallTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('scripts.install_mac'),
                             'Mac installer must be implemented')
        self.api = importlib.import_module('scripts.install_mac')
        uid = patch.object(self.api.os, 'getuid', return_value=789, create=True)
        uid.start()
        self.addCleanup(uid.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.target = self.base / '新的 法库'
        self.runtime = {'system': 'Darwin', 'machine': 'arm64', 'version': [3, 12, 14],
                        'sqlite': '3.46.1', 'fts5_trigram': True,
                        'dependencies': dict.fromkeys(('mcp', 'yaml', 'pypdf', 'pdfplumber',
                                                      'scrapling', 'httpx'), True)}

    def archive(self):
        source = self.base / 'source'
        (source / 'config').mkdir(parents=True)
        (source / 'verification').mkdir()
        corpus = source / 'data/public-corpus/provision-index.json'
        corpus.parent.mkdir(parents=True)
        corpus.write_text(json.dumps({'laws': {'one': {'title': '测试法', 'provisions': [
            {'article': '第一条', 'text': '第一条 测试正文。'}]}}}))
        (source / 'config/shared-library.json').write_text(json.dumps({
            'corpus_path': '../data/public-corpus/provision-index.json',
            'purpose': '个人学习', 'library_id': 'test'}))
        store = LegalStore(source / 'data/legal.sqlite3')
        store.add(law_id='one', title='测试法', text='第一条 测试正文。',
                  source_url='https://example.org/law', locator='第一条', region='CN')
        store.close()
        archive = self.base / 'library.zip'
        export_library(source, archive)
        return archive

    def install_mocked(self, **kwargs):
        with patch.object(self.api, 'check_host'), \
             patch.object(self.api, 'select_python', return_value=Path(sys.executable)), \
             patch.object(self.api, 'probe_runtime', return_value=self.runtime), \
             patch.object(self.api, 'smoke_library', return_value={'ok': True}), \
             patch.object(self.api, 'port_free', return_value=True):
            return self.api.install(self.archive(), self.target, **kwargs)

    def test_unsupported_host_and_child_runtime_rejected(self):
        for system, machine in [('Linux', 'aarch64'), ('Darwin', 'x86_64')]:
            with patch.object(self.api.platform, 'system', return_value=system), \
                 patch.object(self.api.platform, 'machine', return_value=machine):
                with self.assertRaises(ValueError):
                    self.api.check_host()
        for field, value in [('machine', 'x86_64'), ('version', [3, 11]),
                             ('fts5_trigram', False), ('system', 'Linux')]:
            with self.assertRaises(ValueError):
                self.api.validate_runtime(dict(self.runtime, **{field: value}))

    def test_probe_uses_selected_child_interpreter(self):
        with patch.object(self.api.subprocess, 'run', return_value=subprocess.CompletedProcess(
                [], 0, json.dumps(self.runtime), '')) as run:
            result = self.api.probe_runtime(self.base / 'some path/python3')
        self.assertEqual(result, self.runtime)
        self.assertEqual(run.call_args.args[0][0], str(self.base / 'some path/python3'))
        self.assertGreater(run.call_args.kwargs['timeout'], 0)

    def test_existing_target_is_untouched(self):
        self.target.mkdir()
        sentinel = self.target / 'keep.txt'
        sentinel.write_text('keep')
        with self.assertRaises(FileExistsError):
            self.api.install(self.base / 'unused.zip', self.target)
        self.assertEqual(list(self.target.iterdir()), [sentinel])

    def test_failed_pip_retains_failed_state_without_services(self):
        def runner(command, **kwargs):
            if 'pip' in command:
                raise subprocess.CalledProcessError(1, command, stderr='offline')
            return subprocess.CompletedProcess(command, 0, '', '')
        with patch.object(self.api, 'run', side_effect=runner):
            with self.assertRaises(subprocess.CalledProcessError):
                self.install_mocked(profile='search')
        state = json.loads((self.target / 'verification/install/state.json').read_text())
        self.assertEqual(state['status'], 'failed')
        self.assertTrue((self.target / 'data/legal.sqlite3').exists())
        self.assertFalse(list(self.target.rglob('*.plist')))

    def test_search_install_venv_in_final_path_and_no_source_secrets(self):
        with patch.object(self.api, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as run:
            result = self.install_mocked(profile='search')
        commands = [call.args[0] for call in run.call_args_list]
        self.assertIn([str(Path(sys.executable)), '-m', 'venv', str(self.target / '.venv')], commands)
        self.assertTrue(any('requirements-search.txt' in ' '.join(c) for c in commands))
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(len(list((self.target / 'verification/install').glob('*.plist'))), 1)
        self.assertFalse((self.target / 'config/local-machine.json').exists())

    def test_plist_preserves_spaces_chinese_and_loopback_server_arguments(self):
        self.target.mkdir()
        paths = self.api.generate_plists(self.target, include_update=True)
        self.assertEqual(len(paths), 2)
        mcp = plistlib.loads(paths[0].read_bytes())
        self.assertEqual(mcp['ProgramArguments'], [str(self.target / '.venv/bin/python'),
                         str(self.target / 'legal_mcp.py'), '--http'])
        self.assertEqual(mcp['WorkingDirectory'], str(self.target))
        self.assertNotIn('501', str(mcp))
        update = plistlib.loads(paths[1].read_bytes())
        self.assertEqual(update['StartInterval'], 300)

    def test_doctor_distinguishes_missing_dependencies(self):
        self.runtime['dependencies'] = dict.fromkeys(self.runtime['dependencies'], False)
        with patch.object(self.api, 'probe_runtime', return_value=self.runtime), \
             patch.object(self.api, 'port_free', return_value=False), \
             patch.object(Path, 'is_file', return_value=False):
            report = self.api.doctor(self.target)
        for name in ('ready_search', 'ready_pdf', 'ready_doc', 'ready_update'):
            self.assertFalse(report[name])
        self.assertTrue(report['port_conflict'])

    def test_full_install_without_treasury_never_generates_update(self):
        with patch.object(self.api, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')):
            report = self.install_mocked()
        self.assertFalse(report['ready_update'])
        self.assertEqual(len(list((self.target / 'verification/install').glob('*.plist'))), 1)

    def test_machine_paths_are_validated_and_vault_note_is_explicit(self):
        vault = self.base / 'vault'; vault.mkdir()
        result = self.api.machine_settings(obsidian_vault=vault)
        self.assertEqual(result['obsidian_target'], str(vault / 'Songmeng_Law/08_Law/Shared-Library/Live-Inventory.md'))
        with self.assertRaises(ValueError):
            self.api.machine_settings(treasury_root=vault)
        with self.assertRaises(ValueError):
            self.api.machine_settings(soffice=vault)

    def prepare_activation(self, include_update=False):
        doctor = patch.object(self.api, 'doctor', return_value={'ready_search': True, 'ready_update': True})
        doctor.start()
        self.addCleanup(doctor.stop)
        self.target.mkdir()
        plists = self.api.generate_plists(self.target, include_update=include_update)
        (self.target / 'verification/install/state.json').write_text(json.dumps({
            'status': 'complete', 'profile': 'full' if include_update else 'search',
            'plists': [str(path) for path in plists]}))
        agents = self.base / 'LaunchAgents'; agents.mkdir()
        return agents

    def test_activation_refuses_port_conflict_before_writes(self):
        agents = self.prepare_activation()
        with patch.object(self.api, 'check_host'), patch.object(self.api, 'port_free', return_value=False):
            with self.assertRaises(ValueError):
                self.api.activate(self.target, agents_dir=agents)
        self.assertEqual(list(agents.iterdir()), [])

    def test_activation_never_overwrites_existing_agent(self):
        agents = self.prepare_activation()
        old = agents / 'com.chiheng.legal-mcp.plist'; old.write_text('existing')
        with patch.object(self.api, 'check_host'), patch.object(self.api, 'port_free', return_value=True):
            with self.assertRaises(FileExistsError):
                self.api.activate(self.target, agents_dir=agents)
        self.assertEqual(old.read_text(), 'existing')

    def test_failed_first_bootstrap_never_unloads_racing_foreign_service(self):
        agents = self.prepare_activation()
        commands = []
        def runner(command, **kwargs):
            commands.append(command)
            if command[1] == 'bootstrap':
                raise subprocess.CalledProcessError(5, command)
            return subprocess.CompletedProcess(command, 1 if command[1] == 'print' else 0, '', '')
        with patch.object(self.api, 'check_host'), patch.object(self.api, 'port_free', return_value=True), \
             patch.object(self.api.os, 'getuid', return_value=789), patch.object(self.api, 'run', side_effect=runner):
            with self.assertRaises(subprocess.CalledProcessError):
                self.api.activate(self.target, agents_dir=agents)
        self.assertEqual(list(agents.iterdir()), [])
        self.assertFalse(any(command[1] == 'bootout' for command in commands))
        self.assertTrue(any(command[1:3] == ['bootstrap', 'gui/789'] for command in commands))

    def test_later_bootstrap_failure_unloads_only_successfully_registered_label(self):
        agents = self.prepare_activation(include_update=True)
        commands = []
        def runner(command, **kwargs):
            commands.append(command)
            if command[1] == 'bootstrap' and command[-1].endswith('com.menglu.legal-update.plist'):
                raise subprocess.CalledProcessError(5, command)
            return subprocess.CompletedProcess(command, 1 if command[1] == 'print' else 0, '', '')
        with patch.object(self.api, 'check_host'), patch.object(self.api, 'port_free', return_value=True), \
             patch.object(self.api.os, 'getuid', return_value=789), patch.object(self.api, 'run', side_effect=runner):
            with self.assertRaises(subprocess.CalledProcessError):
                self.api.activate(self.target, agents_dir=agents)
        self.assertEqual(list(agents.iterdir()), [])
        self.assertEqual([command for command in commands if command[1] == 'bootout'],
                         [['launchctl', 'bootout', 'gui/789/com.chiheng.legal-mcp']])

    def test_rollback_preserves_agent_file_changed_by_another_process(self):
        agents = self.prepare_activation()
        destination = agents / 'com.chiheng.legal-mcp.plist'
        def runner(command, **kwargs):
            if command[1] == 'bootstrap':
                destination.write_bytes(b'changed by another process')
                raise subprocess.CalledProcessError(5, command)
            return subprocess.CompletedProcess(command, 1, '', '')
        with patch.object(self.api, 'check_host'), patch.object(self.api, 'port_free', return_value=True), \
             patch.object(self.api, 'run', side_effect=runner):
            with self.assertRaises(subprocess.CalledProcessError):
                self.api.activate(self.target, agents_dir=agents)
        self.assertTrue(destination.exists())
        self.assertEqual(destination.read_bytes(), b'changed by another process')

    def test_port_detection_observes_real_bound_socket(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            self.assertFalse(self.api.port_free(listener.getsockname()[1]))

    def test_real_child_checks_sqlite_and_reads_restored_library(self):
        from library_transfer import restore_library
        restore_library(self.archive(), self.target)
        for source in self.api.ROOT.glob('*.py'):
            (self.target / source.name).write_bytes(source.read_bytes())
        runtime = self.api.probe_runtime(sys.executable)
        self.assertTrue(runtime['fts5_trigram'])
        result = self.api.smoke_library(self.target, sys.executable)
        self.assertEqual(result['versions'], 1)
        self.assertEqual(result['mirror_versions'], 1)
        self.assertEqual(result['search_hits'], 1)
        self.assertEqual(result['mirror_hits'], 1)

    def test_full_install_with_treasury_generates_update(self):
        client = self.base / 'treasury/sources/legal-tools/国家法律法规数据库MCP/scripts/client.py'
        client.parent.mkdir(parents=True)
        client.write_text('# external client fixture')
        with patch.object(self.api, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')):
            report = self.install_mocked(treasury_root=self.base / 'treasury')
        self.assertTrue(report['ready_update'])
        self.assertEqual(len(list((self.target / 'verification/install').glob('*.plist'))), 2)

    def test_activation_refuses_loaded_label_without_plist(self):
        agents = self.prepare_activation()
        with patch.object(self.api, 'check_host'), patch.object(self.api, 'port_free', return_value=True), \
             patch.object(self.api, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as run:
            with self.assertRaises(ValueError):
                self.api.activate(self.target, agents_dir=agents)
        self.assertEqual(list(agents.iterdir()), [])
        self.assertEqual([call.args[0][1] for call in run.call_args_list], ['print'])

    def test_activation_checks_runtime_again_before_service_install(self):
        agents = self.prepare_activation()
        with patch.object(self.api, 'check_host'), patch.object(self.api, 'port_free', return_value=True), \
             patch.object(self.api, 'doctor', return_value={'ready_search': False}) as doctor, \
             patch.object(self.api, 'run', return_value=subprocess.CompletedProcess([], 1, '', '')):
            with self.assertRaises(ValueError):
                self.api.activate(self.target, agents_dir=agents)
        doctor.assert_called_once_with(self.target)
        self.assertEqual(list(agents.iterdir()), [])

    def test_present_but_unimportable_treasury_is_not_update_ready(self):
        client = self.base / 'treasury/sources/legal-tools/国家法律法规数据库MCP/scripts/client.py'
        client.parent.mkdir(parents=True)
        client.write_text('import missing_dependency')
        (self.target / 'config').mkdir(parents=True)
        (self.target / 'config/local-machine.json').write_text(json.dumps({'treasury_root': str(self.base / 'treasury')}))
        with patch.object(self.api, 'probe_runtime', return_value=self.runtime), \
             patch.object(self.api, 'smoke_library', return_value={'ok': True}), \
             patch.object(self.api, 'run', side_effect=subprocess.CalledProcessError(1, ['python'])):
            report = self.api.doctor(self.target)
        self.assertTrue(report['ready_search'])
        self.assertFalse(report['ready_update'])
        self.assertTrue(report['errors'])

    def test_smoke_rejects_nonempty_database_with_broken_search_index(self):
        from library_transfer import restore_library
        restore_library(self.archive(), self.target)
        for source in self.api.ROOT.glob('*.py'):
            (self.target / source.name).write_bytes(source.read_bytes())
        with closing(sqlite3.connect(self.target / 'data/legal.sqlite3')) as db:
            db.execute('DELETE FROM search_index')
            db.commit()
        with self.assertRaises(subprocess.CalledProcessError):
            self.api.smoke_library(self.target, sys.executable)

    def test_full_profile_declares_treasury_http_client_dependencies(self):
        requirements = (self.api.ROOT / 'requirements.txt').read_text().splitlines()
        locked = (self.api.ROOT / 'requirements.lock.txt').read_text().splitlines()
        self.assertIn('httpx==0.28.1', requirements)
        self.assertIn('httpx==0.28.1', locked)
        self.assertIn('httpcore==1.0.9', locked)

    def test_activation_requires_every_declared_plist_including_mcp(self):
        agents = self.prepare_activation(include_update=True)
        for label in self.api.LABELS:
            path = self.target / f'verification/install/{label}.plist'
            payload = path.read_bytes()
            path.unlink()
            with self.subTest(label=label), patch.object(self.api, 'check_host'), \
                 patch.object(self.api, 'port_free', return_value=True), \
                 patch.object(self.api, 'run', return_value=subprocess.CompletedProcess([], 1, '', '')) as run:
                with self.assertRaises(ValueError):
                    self.api.activate(self.target, agents_dir=agents)
                self.assertFalse(run.called)
            path.write_bytes(payload)
        self.assertEqual(list(agents.iterdir()), [])

    def test_activation_checks_update_readiness_when_update_declared(self):
        agents = self.prepare_activation(include_update=True)
        with patch.object(self.api, 'check_host'), patch.object(self.api, 'port_free', return_value=True), \
             patch.object(self.api, 'doctor', return_value={'ready_search': True, 'ready_update': False}), \
             patch.object(self.api, 'run', return_value=subprocess.CompletedProcess([], 1, '', '')) as run:
            with self.assertRaises(ValueError):
                self.api.activate(self.target, agents_dir=agents)
        self.assertFalse(any(call.args[0][1] == 'bootstrap' for call in run.call_args_list))
        self.assertEqual(list(agents.iterdir()), [])

    def test_search_activation_ignores_undeclared_update_plist(self):
        agents = self.prepare_activation()
        stray = self.target / 'verification/install/com.menglu.legal-update.plist'
        stray.write_bytes(b'unrelated file')
        with patch.object(self.api, 'check_host'), patch.object(self.api, 'port_free', return_value=True), \
             patch.object(self.api, 'doctor', return_value={'ready_search': True, 'ready_update': False}), \
             patch.object(self.api, 'run', return_value=subprocess.CompletedProcess([], 1, '', '')):
            report = self.api.activate(self.target, agents_dir=agents)
        self.assertEqual(report['labels'], ['com.chiheng.legal-mcp'])
        self.assertEqual([path.name for path in agents.iterdir()], ['com.chiheng.legal-mcp.plist'])

    def test_activation_rejects_unknown_declared_path_and_search_declared_update(self):
        agents = self.prepare_activation()
        state_path = self.target / 'verification/install/state.json'
        original = json.loads(state_path.read_text())
        for extra in [str(self.base / 'outside.plist'),
                      str(self.target / 'verification/install/com.menglu.legal-update.plist')]:
            state = dict(original, plists=original['plists'] + [extra])
            state_path.write_text(json.dumps(state))
            with self.subTest(extra=extra), patch.object(self.api, 'check_host'), \
                 patch.object(self.api, 'port_free', return_value=True), \
                 patch.object(self.api, 'run', return_value=subprocess.CompletedProcess([], 1, '', '')) as run:
                with self.assertRaises(ValueError):
                    self.api.activate(self.target, agents_dir=agents)
                self.assertFalse(run.called)
        self.assertEqual(list(agents.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
