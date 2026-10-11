import json
import tempfile
import unittest
from pathlib import Path
from shared_corpus import PublicCorpus


class CorpusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'corpus.json'
        self.path.write_text(json.dumps({'laws': {'id1': {
            'title': '测试民法典', 'group': '法律', 'status': '有效',
            'effective_date': '2021-01-01', 'urls': ['https://example.org/law'],
            'provisions': [{'article': '第三条', 'text': '民事权益受保护'},
                           {'article': '第三条', 'text': '重复编号不得静默选取'},
                           {'article': '第三条之一', 'text': '权利保护'}]
        }}}), encoding='utf-8')
        self.corpus = PublicCorpus(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_existing_status_never_becomes_verification(self):
        result = self.corpus.search('权益')[0]
        self.assertEqual(result['review_state'], 'unverified_mirror')
        self.assertEqual(result['upstream_status'], '有效')
        self.assertFalse(result['applicability_verified'])

    def test_exact_article_retains_duplicate_and_suffix(self):
        rows = self.corpus.article('id1', '第三条')
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(self.corpus.article('id1', '第三条之一')), 1)
        self.assertNotEqual(rows[0]['fragment_id'], rows[1]['fragment_id'])

    def test_filter_and_literal_search(self):
        self.assertEqual(self.corpus.search('权益', law_title='刑法'), [])
        self.assertEqual(self.corpus.search('*'), [])
        with self.assertRaises(ValueError):
            self.corpus.search('', limit=1)

    def test_counts_are_measured(self):
        self.assertEqual(self.corpus.inventory()['law_versions'], 1)
        self.assertEqual(self.corpus.inventory()['text_units'], 3)

    def test_changed_corpus_reloads(self):
        before = self.corpus.inventory()['corpus_sha256']
        data = json.loads(self.path.read_text())
        data['laws']['id1']['provisions'].append({'article': '第四条', 'text': '新增'})
        self.path.write_text(json.dumps(data), encoding='utf-8')
        after = self.corpus.inventory()
        self.assertNotEqual(before, after['corpus_sha256'])
        self.assertEqual(after['text_units'], 4)

    def test_missing_corpus_does_not_create_empty_database(self):
        missing = PublicCorpus(Path(self.tmp.name) / 'missing.json')
        self.assertFalse(missing.inventory()['available'])
        with self.assertRaises(FileNotFoundError):
            missing.search('权益')


if __name__ == '__main__':
    unittest.main()
