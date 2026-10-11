import copy
import portable_lock as fcntl
import json
import tempfile
import unittest
from unittest.mock import patch
from datetime import date
from pathlib import Path

from law_discovery import run_discovery
import law_discovery


def record(number, when='2026-09-01'):
    return {'bbbs': f'{number:032x}', 'title': f'测试法{number}', 'gbrq': when,
            'sxrq': None, 'sxx': 4, 'zdjgName': '制定机关', 'flxz': '法律'}


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_query_profile_change_archives_old_cursor_before_restart(self):
        await self.run_batch()
        self.calls.clear()
        result=await self.run_batch(query_profile='gbrq_DESC_v1')
        self.assertEqual([x[1] for x in self.calls],[1,2])
        self.assertEqual(result['observed_in_window'],4)
        self.assertTrue(list((self.root/'data/discovery/abandoned').glob('*.json')))

    async def test_restarts_are_bounded_and_require_attention(self):
        await self.run_batch()
        for i in range(3):
            self.rows.append(record(20+i))
            failed=await self.run_batch()
            self.assertTrue(failed['restart_pending'])
            if i<2:await self.run_batch()
        self.calls.clear()
        final=await self.run_batch()
        self.assertTrue(final['requires_attention'])
        self.assertEqual(self.calls,[])

    async def test_drift_archives_scan_and_recovers_same_window_next_run(self):
        await self.run_batch()
        self.rows.append(record(9))
        failed=await self.run_batch()
        self.assertFalse(failed['ok'])
        resumed=await self.run_batch()
        self.assertEqual(resumed['window'],failed['window'])
        self.assertEqual(resumed['observed_in_window'],4)
        self.assertTrue(list((self.root/'data/discovery/abandoned').glob('*.json')))
        self.assertFalse((await self.run_batch())['ok'])
        self.assertTrue((await self.run_batch())['ok'])

    async def test_invalid_page_is_saved_before_validation(self):
        self.rows[0]['gbrq']='2025-01-01'
        self.assertFalse((await self.run_batch())['ok'])
        files=list((self.root/'data/discovery/responses').glob('*.json'))
        self.assertEqual(len(files),1)
        self.assertEqual(json.loads(files[0].read_text())['data']['rows'][0]['gbrq'],'2025-01-01')

    async def test_budget_must_allow_recheck_and_forward_progress(self):
        with self.assertRaises(ValueError):
            await run_discovery(self.root,self.fetch,page_size=2,max_rows=2)

    async def test_state_write_failure_reports_only_persisted_progress(self):
        original=law_discovery.atomic_write
        def failing(path,payload):
            if path.name=='state.json':raise OSError('disk')
            original(path,payload)
        with patch.object(law_discovery,'atomic_write',side_effect=failing):
            report=await self.run_batch()
        self.assertEqual(report['candidate_count'],0)
        self.assertEqual(report['new_candidates_this_run'],0)
        self.assertIsNone(report['last_completed_window'])

    def test_dashboard_reports_partial_and_does_not_claim_ingestion(self):
        text='\n'.join(law_discovery.discovery_lines({'window':{'start':'2026-06-29','end':'2026-09-27'},
             'source_total':1198,'observed_in_window':100,'candidate_count':100,'partial':True,'status':'partial'}))
        self.assertIn('1198',text)
        self.assertIn('100',text)
        self.assertIn('未完成',text)
        self.assertIn('不等于正文入库',text)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.rows = [record(i) for i in range(6)]
        self.calls = []

    async def fetch(self, window, page, size):
        self.calls.append((window.copy(), page, size))
        return {'code': 200, 'total': len(self.rows), 'rows': copy.deepcopy(self.rows[(page-1)*size:page*size])}

    async def run_batch(self, **kwargs):
        return await run_discovery(self.root, self.fetch, today=date(2026,9,27),
                                   page_size=2, max_rows=4, **kwargs)

    async def test_cap_partial_and_resume_with_frozen_window_and_boundary_check(self):
        first = await self.run_batch()
        self.assertTrue(first['partial'])
        self.assertEqual(first['observed_in_window'], 4)
        self.assertIsNone(first['last_completed_window'])
        self.calls.clear()
        second = await run_discovery(self.root, self.fetch, today=date(2026,9,28), page_size=2, max_rows=4)
        self.assertTrue(second['ok'])
        self.assertEqual([x[1] for x in self.calls], [2,3])
        self.assertEqual(second['window']['end'], '2026-09-27')
        self.assertEqual(second['candidate_count'], 6)
        self.assertFalse((self.root / 'data/legal.sqlite3').exists())

    async def test_duplicate_ids_stop_without_advancing(self):
        self.rows[2] = record(0)
        report = await self.run_batch()
        self.assertFalse(report['ok'])
        self.assertEqual(report['observed_in_window'], 2)
        self.assertEqual(report['next_page'], 2)

    async def test_out_of_window_and_missing_metadata_rejected(self):
        for bad in ({'gbrq': '2025-01-01'}, {'bbbs': '../bad'}, {'zdjgName': None}, {'title': ''}):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as tmp:
                self.rows[0].update(bad)
                report = await run_discovery(Path(tmp), self.fetch, today=date(2026,9,27))
                self.assertFalse(report['ok'])
                self.assertEqual(report['candidate_count'], 0)
                self.rows[0] = record(0)

    async def test_boundary_drift_never_advances_cursor(self):
        await self.run_batch()
        self.rows[2]['title'] = '变更'
        report = await self.run_batch()
        self.assertFalse(report['ok'])
        self.assertEqual(report['next_page'], 3)
        self.assertIsNone(report['last_completed_window'])

    async def test_total_changes_fail_and_do_not_erase_candidates(self):
        await self.run_batch()
        self.rows.append(record(9))
        report = await self.run_batch()
        self.assertFalse(report['ok'])
        self.assertEqual(report['candidate_count'], 4)

    async def test_error_redacted_and_cursor_retained(self):
        await self.run_batch()
        async def failed(*args):
            raise RuntimeError('?token=SECRET')
        report = await run_discovery(self.root, failed, today=date(2026,9,27))
        self.assertFalse(report['ok'])
        self.assertEqual(report['next_page'], 3)
        self.assertNotIn('SECRET', json.dumps(report))

    async def test_empty_page_with_positive_total_is_not_complete(self):
        async def empty(*args):
            return {'code':200,'total':10,'rows':[]}
        report = await run_discovery(self.root, empty, today=date(2026,9,27))
        self.assertFalse(report['ok'])
        self.assertTrue(report['partial'])

    async def test_completed_scan_repeats_overlap_without_duplicate_candidates(self):
        self.rows = self.rows[:2]
        self.assertTrue((await self.run_batch())['ok'])
        again = await self.run_batch()
        self.assertEqual(again['candidate_count'], 2)
        self.assertEqual(again['new_candidates_this_run'], 0)

    async def test_lock_and_bad_state_cannot_claim_success(self):
        (self.root / 'verification').mkdir()
        with (self.root / 'verification/law-discovery.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.assertEqual((await self.run_batch())['status'], 'locked')
        (self.root / 'data/discovery').mkdir(parents=True)
        (self.root / 'data/discovery/state.json').write_text('{broken')
        self.assertFalse((await self.run_batch())['ok'])

    async def test_timeout_is_failure(self):
        self.assertFalse((await self.run_batch(timeout=0))['ok'])
