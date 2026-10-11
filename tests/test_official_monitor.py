import asyncio
import copy
import portable_lock as fcntl
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import official_monitor

from official_monitor import run_checks, validate_targets


class MonitorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'original.docx').write_bytes(b'original')
        self.target = {'law_id': 'a' * 32, 'title': '测试法',
                       'original_path': 'original.docx',
                       'original_sha256': hashlib.sha256(b'original').hexdigest(),
                       'metadata': {'sxx': 3, 'gbrq': '2020-01-01', 'sxrq': None,
                                    'zdjgName': '制定机关', 'flxz': '法律'}}
        self.payload = b'original'
        self.metadata = copy.deepcopy(self.target['metadata'])

    async def fetch(self, target):
        self.assertEqual(target['law_id'], 'a' * 32)
        return self.payload, self.metadata

    async def test_unchanged_has_no_snapshot_and_retains_unknown_date(self):
        report = await run_checks(self.root, [self.target], self.fetch)
        self.assertTrue(report['ok'])
        self.assertEqual(report['results'][0]['status'], 'unchanged')
        self.assertEqual(report['results'][0]['missing_date_fields'], ['sxrq'])
        self.assertFalse((self.root / 'data/official-monitor').exists())

    async def test_changed_bytes_saved_once_without_replacing_baseline(self):
        self.payload = b'changed'
        first = await run_checks(self.root, [self.target], self.fetch)
        second = await run_checks(self.root, [self.target], self.fetch)
        row = second['results'][0]
        self.assertEqual(row['status'], 'changed_pending_review')
        self.assertEqual(len(row['pending_snapshots']), 1)
        self.assertEqual(row['pending_snapshots'], first['results'][0]['pending_snapshots'])
        folder = self.root / row['pending_snapshots'][0]
        self.assertEqual((folder / 'original.docx').read_bytes(), b'changed')
        self.assertEqual((self.root / 'original.docx').read_bytes(), b'original')
        self.assertFalse((self.root / 'data/legal.sqlite3').exists())

    async def test_metadata_only_change_is_pending_and_snapshot_is_distinct(self):
        self.metadata['sxx'] = 9
        first = await run_checks(self.root, [self.target], self.fetch)
        self.metadata['sxx'] = 1
        second = await run_checks(self.root, [self.target], self.fetch)
        self.assertEqual(len(second['results'][0]['pending_snapshots']), 2)
        self.assertEqual(first['results'][0]['metadata_changes']['sxx'], {'before': 3, 'after': 9})

    async def test_failure_preserves_last_success_pending_and_redacts_errors(self):
        self.payload = b'changed'
        first = await run_checks(self.root, [self.target], self.fetch)
        async def failed(target):
            raise ValueError('https://example.test/?Signature=SECRET')
        report = await run_checks(self.root, [self.target], failed)
        row = report['results'][0]
        self.assertFalse(report['ok'])
        self.assertEqual(row['status'], 'failed')
        self.assertEqual(row['last_success'], first['results'][0]['last_success'])
        self.assertEqual(row['pending_snapshots'], first['results'][0]['pending_snapshots'])
        self.assertNotIn('SECRET', (self.root / 'verification/official-monitor-latest.json').read_text())

    async def test_return_to_baseline_does_not_dismiss_pending_change(self):
        self.payload = b'changed'
        await run_checks(self.root, [self.target], self.fetch)
        self.payload = b'original'
        report = await run_checks(self.root, [self.target], self.fetch)
        self.assertEqual(report['results'][0]['status'], 'unchanged')
        self.assertEqual(report['pending_documents'], 1)

    async def test_crash_after_snapshot_write_keeps_pending_on_remote_reversion(self):
        class Interrupted(BaseException):
            pass
        write = official_monitor.atomic_write
        def interrupt(path, payload):
            write(path, payload)
            if path.name == 'original.docx':
                raise Interrupted()
        self.payload = b'changed'
        with patch.object(official_monitor, 'atomic_write', side_effect=interrupt):
            with self.assertRaises(Interrupted):
                await run_checks(self.root, [self.target], self.fetch)
        self.payload = b'original'
        report = await run_checks(self.root, [self.target], self.fetch)
        self.assertEqual(report['pending_documents'], 1)

    async def test_timeout_is_failed_not_unchanged(self):
        async def slow(target):
            await asyncio.sleep(1)
        report = await run_checks(self.root, [self.target], slow, timeout=0.01)
        self.assertFalse(report['ok'])
        self.assertTrue(report['complete'])
        self.assertEqual(report['results'][0]['status'], 'failed')

    async def test_lock_prevents_concurrent_check(self):
        (self.root / 'verification').mkdir()
        with (self.root / 'verification/official-monitor.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            report = await run_checks(self.root, [self.target], self.fetch)
        self.assertEqual(report['status'], 'locked')

    async def test_in_progress_is_not_previous_success(self):
        async def check_state(target):
            running = json.loads((self.root / 'verification/official-monitor-latest.json').read_text())
            self.assertFalse(running['complete'])
            self.assertFalse(running['ok'])
            return await self.fetch(target)
        await run_checks(self.root, [self.target], check_state)

    def test_invalid_baselines_rejected_before_network(self):
        for changes in ({'law_id': '../oops'}, {'original_path': '../outside'},
                        {'original_sha256': '0' * 64}, {'metadata': {}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_targets(self.root, [{**self.target, **changes}])
        with self.assertRaises(ValueError):
            validate_targets(self.root, [self.target, self.target])


if __name__ == '__main__':
    unittest.main()
