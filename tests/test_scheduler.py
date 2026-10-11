import portable_lock as fcntl
import importlib
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from legal_store import LegalStore
from scripts import probe_sources


SHANGHAI = ZoneInfo('Asia/Shanghai')


def at(value):
    return datetime.fromisoformat(value).replace(tzinfo=SHANGHAI)


class SchedulerTests(unittest.TestCase):
    def test_partial_official_discovery_is_retryable_and_still_exports(self):
        scheduler = self.scheduler()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'verification').mkdir()
            def run(command, **kwargs):
                return type('Completed', (), {'returncode': 2 if Path(command[1]).name == 'discover_official_laws.py' else 0})()
            with patch.object(scheduler.subprocess, 'run', side_effect=run):
                result = scheduler.execute('national', root)
            self.assertFalse(result['ok'])
            self.assertIn({'script':'discover_official_laws.py','returncode':2},result['commands'])
            self.assertEqual(result['commands'][-1],{'script':'export_obsidian_library.py','returncode':0})

    def test_national_monitor_failure_still_exports_dashboard_and_fails_task(self):
        scheduler = self.scheduler()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'verification').mkdir()
            def run(command, **kwargs):
                return type('Completed', (), {'returncode': int(Path(command[1]).name == 'check_official_originals.py')})()
            with patch.object(scheduler.subprocess, 'run', side_effect=run):
                result = scheduler.execute('national', root)
            self.assertFalse(result['ok'])
            self.assertEqual(result['commands'][-2:], [
                {'script': 'check_official_originals.py', 'returncode': 1},
                {'script': 'export_obsidian_library.py', 'returncode': 0}])

    def scheduler(self):
        spec = importlib.util.find_spec('scripts.scheduled_update')
        self.assertIsNotNone(spec, '需要可复用的 scheduled_update 入口')
        return importlib.import_module('scripts.scheduled_update')

    def test_national_weekdays_and_timezone(self):
        scheduler = self.scheduler()
        self.assertEqual(scheduler.latest_due('national', at('2026-09-28T06:29')), at('2026-09-25T06:30'))
        self.assertEqual(scheduler.latest_due('national', at('2026-09-28T06:30')), at('2026-09-28T06:30'))
        utc = datetime.fromisoformat('2026-09-27T22:30:00+00:00')
        self.assertEqual(scheduler.latest_due('national', utc), at('2026-09-28T06:30'))

    def test_local_weekly_and_monthly_boundaries(self):
        scheduler = self.scheduler()
        self.assertEqual(scheduler.latest_due('local', at('2026-09-28T10:00')), at('2026-09-25T07:00'))
        self.assertEqual(scheduler.latest_due('local', at('2026-09-29T07:00')), at('2026-09-29T07:00'))
        self.assertEqual(scheduler.latest_due('integrity', at('2026-10-04T08:00')), at('2026-10-04T08:00'))
        self.assertEqual(scheduler.latest_due('monthly-coverage', at('2026-10-04T07:59')), at('2026-09-06T08:00'))
        self.assertEqual(scheduler.latest_due('monthly-coverage', at('2026-10-04T08:00')), at('2026-10-04T08:00'))

    def test_first_run_coalesces_missed_periods_and_persists_success(self):
        scheduler = self.scheduler()
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            runner = lambda task: calls.append(task) or {'ok': True}
            scheduler.run_due(root=Path(tmp), now=at('2026-09-28T12:00'), tasks=['national'], runner=runner)
            scheduler.run_due(root=Path(tmp), now=at('2026-09-28T13:00'), tasks=['national'], runner=runner)
            state = json.loads((Path(tmp) / 'verification/scheduler-state.json').read_text())['tasks']['national']
            self.assertEqual(calls, ['national'])
            self.assertEqual(state['last_success_due'], '2026-09-28T06:30:00+08:00')
            self.assertEqual(state['last_attempt'], '2026-09-28T12:00:00+08:00')
            self.assertEqual(state['last_success'], state['last_attempt'])

    def test_failure_preserves_success_and_retries_after_backoff(self):
        scheduler = self.scheduler()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scheduler.run_due(root=root, now=at('2026-09-28T12:00'), tasks=['national'], runner=lambda _: {'ok': True})
            calls = []
            def fails(task):
                calls.append(task)
                raise RuntimeError('connection failed')
            scheduler.run_due(root=root, now=at('2026-09-29T07:00'), tasks=['national'], runner=fails)
            scheduler.run_due(root=root, now=at('2026-09-29T07:01'), tasks=['national'], runner=fails)
            state = json.loads((root / 'verification/scheduler-state.json').read_text())['tasks']['national']
            self.assertEqual(len(calls), 1)
            self.assertEqual(state['status'], 'failed')
            self.assertNotIn('result', state)
            self.assertEqual(state['last_success_due'], '2026-09-28T06:30:00+08:00')
            self.assertIn('connection failed', state['error'])
            scheduler.run_due(root=root, now=at('2026-09-29T07:16'), tasks=['national'], runner=lambda _: {'ok': True})
            state = json.loads((root / 'verification/scheduler-state.json').read_text())['tasks']['national']
            self.assertEqual(state['status'], 'succeeded')
            self.assertEqual(state['failures'], 0)

    def test_non_reentrant_lock_prevents_execution(self):
        scheduler = self.scheduler()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'verification').mkdir()
            with (root / 'verification/scheduler.lock').open('w') as handle:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = scheduler.run_due(root=root, now=at('2026-09-28T12:00'), runner=lambda _: self.fail('must not run'))
                self.assertEqual(result['status'], 'locked')

    def test_interrupted_running_state_is_recovered_on_next_run(self):
        scheduler = self.scheduler()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'verification').mkdir()
            (root / 'verification/scheduler-state.json').write_text(json.dumps({'tasks': {'national': {
                'status': 'running', 'last_attempt': '2026-09-28T07:00:00+08:00'}}}))
            result = scheduler.run_due(root=root, now=at('2026-09-28T08:00'), tasks=['national'], runner=lambda _: {'ok': True})
            self.assertEqual(result['tasks']['national']['status'], 'succeeded')

    def test_monthly_still_writes_report_when_health_probe_fails(self):
        scheduler = self.scheduler()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'verification').mkdir()
            calls = []
            def run(command, **kwargs):
                calls.append(command)
                return type('Completed', (), {'returncode': 1 if 'probe_sources.py' in command[1] else 0})()
            with patch.object(scheduler.subprocess, 'run', side_effect=run):
                result = scheduler.execute('monthly-coverage', root)
            self.assertFalse(result['ok'])
            scripts = {Path(command[1]).name: command for command in calls}
            self.assertEqual(scripts['probe_sources.py'][-2:], ['--group', 'all'])
            self.assertEqual(scripts['integrity_report.py'][-2:], ['--kind', 'monthly-coverage'])

    def test_integrity_exports_dashboard_and_propagates_export_failure(self):
        scheduler = self.scheduler()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'verification').mkdir()
            calls = []
            def run(command, **kwargs):
                calls.append(Path(command[1]).name)
                return type('Completed', (), {'returncode': int(calls[-1] == 'export_obsidian_library.py')})()
            with patch.object(scheduler.subprocess, 'run', side_effect=run):
                result = scheduler.execute('integrity', root)
            self.assertEqual(calls, ['integrity_report.py', 'export_obsidian_library.py'])
            self.assertFalse(result['ok'])

    def test_failed_integrity_report_does_not_export_dashboard(self):
        scheduler = self.scheduler()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'verification').mkdir()
            calls = []
            def run(command, **kwargs):
                calls.append(Path(command[1]).name)
                return type('Completed', (), {'returncode': 1})()
            with patch.object(scheduler.subprocess, 'run', side_effect=run):
                result = scheduler.execute('integrity', root)
            self.assertEqual(calls, ['integrity_report.py'])
            self.assertFalse(result['ok'])

    def test_national_and_monthly_refresh_catalog_once_before_probing(self):
        scheduler = self.scheduler()
        for task in ('national', 'monthly-coverage'):
            with self.subTest(task=task), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / 'verification').mkdir()
                calls = []
                def run(command, **kwargs):
                    calls.append(Path(command[1]).name)
                    return type('Completed', (), {'returncode': 0})()
                with patch.object(scheduler.subprocess, 'run', side_effect=run):
                    result = scheduler.execute(task, root)
                self.assertTrue(result['ok'])
                self.assertEqual(calls[:2], ['refresh_upstream_catalog.py', 'probe_sources.py'])
                self.assertEqual(calls.count('refresh_upstream_catalog.py'), 1)
                if task == 'monthly-coverage':
                    self.assertEqual(calls[2:], ['integrity_report.py', 'export_obsidian_library.py'])

    def test_catalog_refresh_failure_propagates_to_task(self):
        scheduler = self.scheduler()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'verification').mkdir()
            def run(command, **kwargs):
                return type('Completed', (), {'returncode': int(Path(command[1]).name == 'refresh_upstream_catalog.py')})()
            with patch.object(scheduler.subprocess, 'run', side_effect=run):
                result = scheduler.execute('national', root)
            self.assertFalse(result['ok'])


class SourceHealthTests(unittest.TestCase):
    def report_root(self, root):
        LegalStore(root / 'data/legal.sqlite3').close()
        (root / 'config').mkdir()
        (root / 'config/sources.json').write_text('{"sources": []}')
        (root / 'config/coverage-targets.yaml').write_text('{"regions": [], "source_categories": []}')

    def test_monthly_keeps_catalog_and_review_counts_separate_from_publication(self):
        from review_records import append_record
        integrity = importlib.import_module('scripts.integrity_report')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.report_root(root)
            (root / 'data/upstream-catalog').mkdir()
            (root / 'data/upstream-catalog/latest.json').write_text(json.dumps({
                'status': 'updated', 'scope': 'catalogue_only_unverified',
                'checked_at_utc': '2026-09-27T08:00:00+00:00', 'snapshot': 'snapshots/test',
                'upstream_records': 5, 'local_records': 2, 'shared_ids': 2,
                'upstream_only_ids': 3, 'local_only_ids': 0}))
            record = {'source_kind': 'statute', 'source_url': 'https://example.org/law',
                'locator': '第一条', 'content_sha256': 'a' * 64, 'reviewer': 'test',
                'reviewer_kind': 'automated', 'checked_at': '2026-09-27T08:00:00+00:00',
                'result': 'match', 'scope': 'fragment'}
            append_record(root / 'data/review-records.jsonl', record)
            append_record(root / 'data/review-records.jsonl', {**record, 'reviewer_kind': 'human', 'scope': 'entire_law'})
            append_record(root / 'data/review-records.jsonl', {**record, 'reviewer_kind': 'human',
                'source_kind': 'guiding_case', 'scope': 'entire_case',
                'case_reference_status': 'unverified', 'judgment_validity': 'effective'})
            with patch('builtins.print'):
                report = integrity.main('monthly-coverage', root=root)
            self.assertIn('upstream_catalog', report)
            self.assertEqual(report['upstream_catalog']['upstream_only_ids'], 3)
            self.assertEqual(report['upstream_catalog']['scope'], 'catalogue_only_unverified')
            self.assertEqual(report['upstream_catalog']['checked_at_utc'], '2026-09-27T08:00:00+00:00')
            self.assertEqual(report['upstream_catalog']['snapshot'], 'snapshots/test')
            self.assertEqual(report['review_records']['total'], 3)
            self.assertEqual(report['review_records']['by_reviewer_kind'], {'human': 2, 'automated': 1})
            self.assertEqual(report['review_records']['by_scope'], {'fragment': 1, 'entire_law': 1, 'entire_case': 1})
            self.assertEqual(report['review_records']['by_reviewer_and_scope']['automated']['fragment'], 1)
            self.assertEqual(report['published'], 0)
            self.assertFalse(report['checks']['lawyer_review_performed'])

    def test_missing_catalog_and_ledger_have_explicit_missing_status(self):
        integrity = importlib.import_module('scripts.integrity_report')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.report_root(root)
            with patch('builtins.print'):
                report = integrity.main(root=root)
            self.assertIn('upstream_catalog', report)
            self.assertEqual(report['upstream_catalog']['status'], 'missing')
            self.assertEqual(report['review_records']['status'], 'missing')
            self.assertEqual(report['review_records']['total'], 0)

    def test_broken_catalog_or_ledger_json_fails_without_overwriting_last_report(self):
        integrity = importlib.import_module('scripts.integrity_report')
        for name in ('upstream-catalog/latest.json', 'review-records.jsonl'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.report_root(root)
                broken = root / 'data' / name
                broken.parent.mkdir(parents=True, exist_ok=True)
                broken.write_text('{broken json\n')
                latest = root / 'verification/integrity-latest.json'
                latest.parent.mkdir()
                latest.write_text('{"last_good": true}')
                with self.assertRaises(ValueError), patch('builtins.print'):
                    integrity.main(root=root)
                self.assertEqual(json.loads(latest.read_text()), {'last_good': True})

    def test_storage_error_cannot_be_reported_as_quarantined_success(self):
        from scrapling.engines.toolbelt.custom import Response
        def fetch(url):
            content = '<title>官方发布</title><main>' + '公开法律条文。' * 100 + '</main>'
            if url.endswith('/robots.txt'):
                content = 'User-agent: *\nDisallow:'
            return Response(url=url, content=content, status=200, reason='OK', cookies={}, headers={}, request_headers={})
        class BrokenStore:
            def add(self, **kwargs):
                raise RuntimeError('database is locked')
        with tempfile.TemporaryDirectory() as tmp:
            row = probe_sources.probe_source({'source_id': 'law', 'url': 'https://official.gov.cn/law',
                'region': 'CN', 'document': True}, directory=Path(tmp), store=BrokenStore(), fetch=fetch, delay=0)
        self.assertEqual(row['state'], 'storage_error')
        self.assertIn('database is locked', row['error'])

    def test_group_merge_preserves_other_source_and_last_good_snapshot(self):
        merge = getattr(probe_sources, 'merge_health', None)
        self.assertIsNotNone(merge, '分组探测必须合并，而不能覆盖其它来源')
        old = [{'source_id': 'national', 'state': 'quarantined', 'attempted_at': '2026-09-01', 'sha256': 'good'},
               {'source_id': 'local', 'state': 'quarantined', 'attempted_at': '2026-09-02'}]
        result = {r['source_id']: r for r in merge(old, [{'source_id': 'national', 'state': 'failed', 'attempted_at': '2026-09-03'}])}
        self.assertEqual(result['local']['attempted_at'], '2026-09-02')
        self.assertEqual(result['national']['last_success'], '2026-09-01')
        self.assertEqual(result['national']['last_attempt'], '2026-09-03')
        self.assertEqual(result['national']['last_good_snapshot']['sha256'], 'good')

    def test_http_fallback_remains_observation_and_keeps_https_error(self):
        probe = getattr(probe_sources, 'probe_source', None)
        self.assertIsNotNone(probe)
        from scrapling.engines.toolbelt.custom import Response
        content = ('<html><title>长春市人民政府</title><main>' + '公开政府栏目。' * 100 + '</main></html>').encode()
        def fetch(url):
            if url.startswith('https:'):
                raise RuntimeError('TLS handshake failed')
            body = b'User-agent: *\nDisallow:' if url.endswith('/robots.txt') else content
            return Response(url=url, content=body, status=200, reason='OK', cookies={}, headers={}, request_headers={})
        with tempfile.TemporaryDirectory() as tmp:
            result = probe({'source_id': 'cc', 'url': 'https://www.changchun.gov.cn/',
                'fallback_urls': ['http://www.changchun.gov.cn/'], 'region': 'CN-JL-CC', 'document': False},
                directory=Path(tmp), store=None, fetch=fetch, delay=0)
            self.assertEqual(result['state'], 'quarantined')
            self.assertEqual(result['transport_security'], 'unencrypted')
            self.assertFalse(result['document'])
            self.assertIn('TLS handshake failed', result['attempts'][0]['error'])

    def test_robots_or_challenge_denial_does_not_try_fallback(self):
        probe = getattr(probe_sources, 'probe_source', None)
        self.assertIsNotNone(probe)
        class Blocked:
            status = 403
            body = b''
        calls = []
        def fetch(url):
            calls.append(url)
            return Blocked()
        with tempfile.TemporaryDirectory() as tmp:
            result = probe({'source_id': 'cc', 'url': 'https://www.changchun.gov.cn/',
                'fallback_urls': ['http://www.changchun.gov.cn/'], 'region': 'CN-JL-CC', 'document': False},
                directory=Path(tmp), store=None, fetch=fetch, delay=0)
        self.assertEqual(result['state'], 'manual_required')
        self.assertEqual(len(calls), 1)

    def test_integrity_uses_actual_rows_and_source_health(self):
        # Importing the report must have no write side effect.
        integrity = importlib.import_module('scripts.integrity_report')
        build = getattr(integrity, 'build_report', None)
        self.assertIsNotNone(build, '完整性报告需要可测试的实时汇总')
        with tempfile.TemporaryDirectory() as tmp:
            store = LegalStore(Path(tmp) / 'legal.sqlite3')
            try:
                for i in range(3):
                    store.add(law_id=f'law-{i}', title=f'规范{i}', text=f'条款正文{i}',
                        source_url=f'https://official.gov.cn/{i}', locator='第一条', region='CN-JL')
                report = build(store=store, sources=[{'source_id': 'jl', 'region': 'CN-JL', 'region_name': '吉林', 'document': False}],
                    health=[{'source_id': 'jl', 'state': 'quarantined', 'transport_security': 'verified_tls'}],
                    targets={'regions': ['吉林', '北京'], 'source_categories': ['法院发布']})
                self.assertEqual(report['versions'], 3)
                self.assertEqual(report['coverage']['regions_with_stored_documents'], ['CN-JL'])
                self.assertEqual(report['coverage']['province_targets'], 2)
                self.assertEqual(report['sources']['reachable'], 1)
                self.assertFalse(report['coverage_complete'])
                self.assertIn('北京', report['coverage']['province_targets_without_documents'])
            finally:
                store.close()

    def test_integrity_includes_shared_corpus_without_promoting_mirror(self):
        integrity = importlib.import_module('scripts.integrity_report')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            LegalStore(root / 'data/legal.sqlite3').close()
            (root / 'config').mkdir()
            (root / 'config/sources.json').write_text('{"sources": []}')
            (root / 'config/coverage-targets.yaml').write_text('{"regions": [], "source_categories": []}')
            corpus = root / 'public-index.json'
            corpus.write_text(json.dumps({'laws': {'one': {'title': '测试公开法规', 'provisions': [{'text': '第一条'}]}}}))
            (root / 'config/shared-library.json').write_text(json.dumps({'corpus_path': str(corpus)}))
            with patch('builtins.print'):
                report = integrity.main('monthly-coverage', root=root)
            self.assertIn('shared_offline_corpus', report)
            self.assertEqual(report['shared_offline_corpus']['law_versions'], 1)
            self.assertEqual(report['shared_offline_corpus']['text_units'], 1)
            self.assertEqual(report['shared_offline_corpus']['review_state'], 'unverified_mirror')
            self.assertEqual(report['versions'], 0)
            self.assertFalse(report['checks']['lawyer_review_performed'])
            self.assertEqual(len(list((root / 'verification/monthly').glob('*.json'))), 1)

    def test_missing_database_is_not_created_by_health_check(self):
        integrity = importlib.import_module('scripts.integrity_report')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(Exception):
                integrity.main(root=root)
            self.assertFalse((root / 'data/legal.sqlite3').exists())


if __name__ == '__main__':
    unittest.main()
