import asyncio
import contextlib
import io
import json
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from law_discovery import discovery_lines
from official_monitor import dashboard_lines
from scripts import check_official_originals, discover_official_laws, ingest_basic_laws, scheduled_update
from scripts.test_windows_offline import offline_connections


CASES = (
    (discover_official_laws, 'main', (), 'law-discovery-latest.json'),
    (check_official_originals, 'check_known_originals', (), 'official-monitor-latest.json'),
    (ingest_basic_laws, 'main', ('basic-laws',), 'basic-laws-ingestion-latest.json'),
    (ingest_basic_laws, 'main', ('supporting-rules',), 'supporting-rules-ingestion-latest.json'),
)


class OfficialAccessTests(unittest.TestCase):
    def test_blocked_renderers_show_reason_evidence_and_history_without_counts(self):
        for render in (discovery_lines, dashboard_lines):
            for previous in ('verification/access-blocked-history/old-evidence.json', None):
                with self.subTest(renderer=render.__name__, previous=previous):
                    report = {'status': 'access_blocked', 'ok': False, 'complete': False,
                              'reason': '来源禁止自动化采集',
                              'evidence': {'url': 'https://flk.npc.gov.cn/robots.txt'},
                              'candidate_count': 123456,
                              'results': [{'status': 'unchanged', 'pending_snapshots': ['old']}],
                              'previous_report': previous}
                    text = '\n'.join(render(report))
                    self.assertIn('access_blocked', text)
                    self.assertIn('本次未检查', text)
                    self.assertIn(report['reason'], text)
                    self.assertIn('(https://flk.npc.gov.cn/robots.txt)', text)
                    self.assertIn('历史', text)
                    self.assertNotIn('123456', text)
                    self.assertNotIn('：0', text)
                    self.assertNotIn('0份', text)
                    self.assertNotIn('有待审变化的文件：1', text)
                    if previous:
                        self.assertIn('(' + previous + ')', text)
                    else:
                        self.assertIn('未附旧报告链接', text)

    def test_deeply_nested_old_json_is_preserved_as_unparseable_evidence(self):
        # JSON decoder recursion limits vary between Python builds.
        for depth in (1100, 10000):
            with self.subTest(depth=depth), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                latest = root / 'verification/law-discovery-latest.json'
                latest.parent.mkdir()
                old = b'[' * depth + b'0' + b']' * depth
                latest.write_bytes(old)
                try:
                    result = self.invoke(discover_official_laws, 'main', (), root)
                except RecursionError:
                    self.fail('Deep old JSON must be archived without preventing access blocking')
                self.assert_blocked(result)
                self.assertTrue(result['report_persisted'])
                self.assertEqual((root / result['previous_report']).read_bytes(), old)

    def assert_blocked(self, result):
        self.assertIsInstance(result, dict)
        self.assertIs(result['ok'], False)
        self.assertIs(result.get('complete'), False)
        self.assertEqual(result.get('status'), 'access_blocked')
        self.assertIn('禁止', result['reason'])
        self.assertEqual(result['evidence']['url'], 'https://flk.npc.gov.cn/robots.txt')
        self.assertEqual(result['evidence']['observed_on'], '2026-09-28')
        self.assertEqual(result['evidence']['sha256'],
                         '69af1c653106e97435ff756e86a8baefd9876c656fe5828fe692744d48fafe9d')
        self.assertEqual(json.loads(json.dumps(result)), result)

    def invoke(self, module, entry, args, root):
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(module, 'ROOT', root))
            for owner, name in ((module, 'require_treasury'), (ingest_basic_laws, 'LegalStore')):
                stack.enter_context(patch.object(owner, name, side_effect=AssertionError(name + ' must not run')))
            stack.enter_context(offline_connections())
            stack.enter_context(patch.dict(sys.modules, {'client': None, 'httpx': None}))
            try:
                return asyncio.run(getattr(module, entry)(*args))
            except FileNotFoundError as error:
                self.fail('The access guard must precede configuration reads: ' + str(error))

    def test_each_entry_blocks_before_config_dependencies_network_and_database(self):
        for module, entry, args, name in CASES:
            with self.subTest(report=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                state = root / 'data/discovery/state.json'
                state.parent.mkdir(parents=True)
                state.write_bytes(b'{"active":{"next_page":7},"catalog":{"old":true}}')
                database = root / 'data/legal.sqlite3'
                database.write_bytes(b'untouched database fixture')
                originals = {p: p.read_bytes() for p in (state, database)}
                result = self.invoke(module, entry, args, root)
                self.assert_blocked(result)
                self.assertEqual({p: p.read_bytes() for p in originals}, originals)
                self.assertEqual(json.loads((root / 'verification' / name).read_text()), result)
                self.assertEqual(set((root / 'data').rglob('*')), {state.parent, state, database})

    def test_preserves_old_success_failure_and_invalid_reports_with_idempotent_retries(self):
        for module, entry, args, name in CASES:
            for old in (b'{"ok":true,"results":[{"last_success":"old"}]}\n',
                        b'{"ok":false,"error":"prior failure"}\n', b'{interrupted json'):
                with self.subTest(report=name, old=old), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    latest = root / 'verification' / name
                    latest.parent.mkdir()
                    latest.write_bytes(old)
                    result = self.invoke(module, entry, args, root)
                    self.assert_blocked(result)
                    retained = root / result['previous_report']
                    self.assertEqual(retained.read_bytes(), old)
                    before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
                    repeated = self.invoke(module, entry, args, root)
                    self.assertEqual(repeated, result)
                    self.assertEqual({p: p.read_bytes() for p in root.rglob('*') if p.is_file()}, before)

    def test_report_backup_failure_never_overwrites_old_evidence(self):
        cases = CASES + ((check_official_originals, 'main', (), 'official-monitor-latest.json'),)
        for module, entry, args, name in cases:
            with self.subTest(report=name, entry=entry), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                latest = root / 'verification' / name
                latest.parent.mkdir()
                latest.write_bytes(b'old success evidence')
                with patch('official_access.atomic_write', side_effect=OSError('disk unavailable')):
                    try:
                        result = self.invoke(module, entry, args, root)
                    except OSError:
                        self.fail('Storage failure must still return the access-blocked report')
                self.assert_blocked(result)
                self.assertIs(result['report_persisted'], False)
                self.assertIn('保存失败', result['report_error'])
                self.assertEqual(latest.read_bytes(), b'old success evidence')

    def cold_cli(self, module, args, root, *, fail_save=False):
        source = Path(ingest_basic_laws.__file__).resolve().parents[1]
        for path in source.glob('*.py'):
            shutil.copyfile(path, root / path.name)
        (root / 'scripts').mkdir(exist_ok=True)
        for script in {Path(case[0].__file__) for case in CASES} | {source / 'scripts/test_windows_offline.py'}:
            shutil.copyfile(script, root / 'scripts' / script.name)
        script = root / 'scripts' / Path(module.__file__).name
        code = '''import runpy, sys
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
from scripts.test_windows_offline import offline_connections
sys.argv = sys.argv[2:]
with offline_connections(), \\
     patch('sqlite3.connect', side_effect=AssertionError('database')), \\
     patch.dict(sys.modules, {'client': None, 'httpx': None}):
    from scripts.ingest_basic_laws import batch_targets, public_object_url
    assert len(batch_targets('basic-laws')) == 6
    assert public_object_url('https://flkoss.obs-bj2.cucloud.cn/a.docx', 'a.docx')
    SAVE_PATCH
'''
        run = "runpy.run_path(sys.argv[0], run_name='__main__')"
        save_patch = ("with patch('official_access.atomic_write', side_effect=OSError('disk unavailable')):\n        "
                      + run) if fail_save else run
        code = code.replace('SAVE_PATCH', save_patch)
        completed = subprocess.run([sys.executable, '-c', code, str(root), str(script)]
                                   + (['--batch', args[0]] if args else []),
                                   cwd=root, capture_output=True, text=True, timeout=15)
        self.assertNotEqual(completed.returncode, 0)
        try:
            result = json.loads(completed.stdout)
        except ValueError:
            self.fail('Cold CLI must emit blocked JSON: ' + completed.stderr[-1000:] + completed.stdout)
        self.assert_blocked(result)
        return result

    def test_cold_cli_blocks_before_broken_machine_settings_and_keeps_helpers_importable(self):
        for module, _, args, name in CASES:
            for config in ('{broken', '{"unexpected_setting":true}'):
                with self.subTest(report=name, config=config), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    (root / 'config').mkdir()
                    settings = root / 'config/local-machine.json'
                    settings.write_text(config)
                    result = self.cold_cli(module, args, root)
                    self.assertTrue(result['report_persisted'])
                    self.assertEqual(settings.read_text(), config)
                    self.assertFalse((root / 'data').exists())

    def test_cold_cli_reports_backup_failure_without_losing_block_or_old_report(self):
        for module, _, args, name in CASES:
            with self.subTest(report=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                latest = root / 'verification' / name
                latest.parent.mkdir()
                latest.write_bytes(b'old success evidence')
                result = self.cold_cli(module, args, root, fail_save=True)
                self.assertIs(result['report_persisted'], False)
                self.assertIn('保存失败', result['report_error'])
                self.assertEqual(latest.read_bytes(), b'old success evidence')
                self.assertFalse((root / 'data').exists())

    def test_cli_prints_serializable_block_reason_and_exits_nonzero(self):
        for module, _, args, name in CASES:
            with self.subTest(report=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                scripts = root / 'scripts'
                scripts.mkdir()
                script = scripts / Path(module.__file__).name
                shutil.copyfile(module.__file__, script)
                argv = [str(script)] + (['--batch', args[0]] if args else [])
                output = io.StringIO()
                with patch.object(sys, 'argv', argv), contextlib.redirect_stdout(output), \
                        patch.dict(sys.modules, {'client': None, 'httpx': None}), \
                        patch('local_settings.require_treasury', side_effect=AssertionError('dependencies')):
                    with self.assertRaises(SystemExit) as raised:
                        runpy.run_path(str(script), run_name='__main__')
                self.assertIsInstance(raised.exception.code, int)
                self.assertNotEqual(raised.exception.code, 0)
                self.assert_blocked(json.loads(output.getvalue()))

    def test_scheduler_continues_after_blocked_commands_and_runs_other_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'verification').mkdir()
            calls = []
            def run(command, **kwargs):
                name = Path(command[1]).name
                calls.append(name)
                code = 0
                if name in ('discover_official_laws.py', 'check_official_originals.py'):
                    case = next(row for row in CASES if Path(row[0].__file__).name == name)
                    result = self.invoke(*case[:3], root)
                    self.assert_blocked(result)
                    code = 2
                return type('Completed', (), {'returncode': code})()
            with patch.object(scheduled_update.subprocess, 'run', side_effect=run):
                national = scheduled_update.execute('national', root)
                self.assertFalse(national['ok'])
                self.assertEqual(calls[-3:], ['discover_official_laws.py', 'check_official_originals.py',
                                              'export_obsidian_library.py'])
                self.assertTrue(scheduled_update.execute('local', root)['ok'])
                self.assertTrue(scheduled_update.execute('integrity', root)['ok'])
                self.assertEqual(calls[-3:], ['probe_sources.py', 'integrity_report.py',
                                            'export_obsidian_library.py'])
