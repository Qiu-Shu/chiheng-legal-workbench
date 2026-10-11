import tempfile
import sqlite3
import unittest
from pathlib import Path
from legal_store import LegalStore


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = LegalStore(Path(self.tmp.name) / 'test.sqlite3')

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def add(self, **overrides):
        values = dict(law_id='demo', title='测试法规', text='第一条 举证责任和自认。',
                      source_url='https://example.org/law', locator='第一条', region='CN')
        values.update(overrides)
        return self.store.add(**values)

    def test_unreviewed_is_not_authority(self):
        self.add()
        self.assertEqual(self.store.search('自认', include_quarantine=False), [])
        self.assertEqual(len(self.store.search('自认')), 1)
        self.assertEqual(len(self.store.search('自认', include_quarantine=True)), 1)

    def test_dedup_and_versions(self):
        old = self.add()
        self.assertEqual(old, self.add())
        new = self.add(text='第二条 新举证责任规则。')
        self.assertNotEqual(old, new)
        self.assertEqual(self.store.detail(old)['text'], '第一条 举证责任和自认。')

    def test_atomic_source_conflict_preserves_existing_version_and_audit(self):
        key=self.add(provenance={'publisher':'原机关'})
        before=self.store.detail(key)
        audits=self.store.db.execute('SELECT count(*) FROM audit').fetchone()[0]
        with self.assertRaisesRegex(ValueError,'拒绝覆盖'):
            self.add(provenance={'publisher':'不同机关'})
        self.assertEqual(self.store.detail(key),before)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM audit').fetchone()[0],audits)
        self.assertEqual(self.store.health()['versions'],1)

    def test_atomic_roundtrip_failure_rolls_back_all_new_rows(self):
        self.store.db.executescript("CREATE TRIGGER corrupt_roundtrip AFTER INSERT ON provenance BEGIN UPDATE versions SET text='corrupt' WHERE version_id=NEW.version_id; END;")
        with self.assertRaisesRegex(ValueError,'回读不一致'):
            self.add(provenance={'publisher':'测试机关'})
        for table in ('versions','search_index','provenance','audit'):
            self.assertEqual(self.store.db.execute('SELECT count(*) FROM '+table).fetchone()[0],0,table)

    def test_temporal_filter_and_region(self):
        old = self.add()
        self.store.approve(old, reviewer='test-human', effective_from='2020-01-01', effective_to='2021-01-01')
        new = self.add(text='新举证责任规则', region='CN-JL')
        self.store.approve(new, reviewer='test-human', effective_from='2021-01-01')
        self.assertEqual([r['version_id'] for r in self.store.search('举证责任', as_of='2020-06-01', region='CN-JL')], [old])
        self.assertEqual(self.store.search('举证责任', as_of='2022-01-01', region='CN-GD'), [])
        self.assertEqual([r['version_id'] for r in self.store.search('举证责任', as_of='2022-01-01', region='CN-JL')], [new])

    def test_revoke_retains_original(self):
        key = self.add()
        self.store.approve(key, reviewer='test-human', effective_from='2020-01-01')
        self.assertEqual(len(self.store.search('自认')), 1)
        self.store.revoke(key, reviewer='test-human', reason='错误版本')
        self.assertEqual(self.store.search('自认'), [])
        self.assertIsNotNone(self.store.detail(key))

    def test_invalid_metadata(self):
        key = self.add()
        for start, end in [('bad', None), ('2022-01-01', '2021-01-01')]:
            with self.assertRaises(ValueError):
                self.store.approve(key, reviewer='human', effective_from=start, effective_to=end)
        with self.assertRaises(ValueError):
            self.store.approve(key, reviewer='', effective_from='2020-01-01')

    def test_literal_query_no_sql_or_fts_injection(self):
        self.add()
        self.assertEqual(self.store.search("' OR 1=1 --", include_quarantine=True), [])
        self.assertEqual(self.store.search('*', include_quarantine=True), [])

    def test_citation_payload(self):
        key = self.add()
        row = self.store.search('自认', include_quarantine=True)[0]
        for field in ('source_url', 'locator', 'sha256', 'fetched_at', 'review_state', 'version_id'):
            self.assertTrue(row[field])
        self.assertEqual(row['version_id'], key)

    def test_readonly_missing_database_fails_without_creating_it(self):
        missing = Path(self.tmp.name) / 'absent.sqlite3'
        with self.assertRaises(sqlite3.OperationalError):
            LegalStore(missing, readonly=True)
        self.assertFalse(missing.exists())

    def test_readonly_blocks_write(self):
        key = self.add()
        reader = LegalStore(Path(self.tmp.name) / 'test.sqlite3', readonly=True)
        try:
            self.assertEqual(reader.detail(key)['title'], '测试法规')
            with self.assertRaises(sqlite3.OperationalError):
                reader.revoke(key, reviewer='test', reason='不能写')
        finally:
            reader.close()


if __name__ == '__main__':
    unittest.main()
