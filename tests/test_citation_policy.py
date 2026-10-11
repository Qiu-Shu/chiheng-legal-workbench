import hashlib
import tempfile
import unittest
from pathlib import Path

import legal_mcp
from legal_store import LegalStore


class CitationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.before = legal_mcp.DB
        legal_mcp.DB = Path(self.tmp.name) / 'law.sqlite3'
        self.store = LegalStore(legal_mcp.DB)

    def tearDown(self):
        self.store.close()
        legal_mcp.DB = self.before
        self.tmp.cleanup()

    def add(self, **extra):
        return self.store.add(law_id='test', title='测试法规', text='第一条 测试正文。\n\n第二条 后页内容。',
                              source_url='https://example.org/detail', locator='保存全文', region='CN', **extra)

    def test_unreviewed_text_is_searchable_by_default_but_not_approved(self):
        version = self.add()
        self.assertEqual([r['version_id'] for r in self.store.search('测试法规')], [version])
        result = legal_mcp.search_law('测试法规')['results']
        self.assertEqual([r['version_id'] for r in result], [version])
        self.assertEqual(result[0]['review_state'], 'quarantine')
        self.assertEqual(legal_mcp.search_law('测试法规', include_quarantine=False)['results'], [])
        self.assertEqual(self.store.health()['published'], 0)

    def test_revoked_text_is_excluded_even_when_unreviewed_is_included(self):
        version = self.add()
        self.store.revoke(version, reviewer='test', reason='提取有错')
        self.assertEqual(self.store.search('测试法规', include_quarantine=True), [])
        fragment = legal_mcp.get_law_fragment(version)
        self.assertTrue(fragment['found'])
        self.assertEqual(fragment['citation']['availability'], 'withdrawn')
        self.store.approve(version, reviewer='test', effective_from='2020-01-01')
        self.assertEqual(len(self.store.search('测试法规')), 1)

    def test_unknown_fields_are_explicit_on_search_article_and_fragment(self):
        version = self.add()
        rows = [legal_mcp.search_law('测试法规', include_quarantine=True)['results'][0],
                legal_mcp.get_law_fragment(version), legal_mcp.get_law_article(version, '第一条')]
        for row in rows:
            self.assertIn('citation', row)
            citation = row['citation']
            self.assertEqual(citation['source_url'], 'https://example.org/detail')
            self.assertEqual(citation['version_id'], version)
            self.assertIsNone(citation['publisher'])
            self.assertIsNone(citation['effective_from'])
            self.assertIn('publisher', citation['missing_fields'])
            self.assertTrue(citation['review_at_use_required'])
            self.assertFalse(citation['legal_applicability_verified'])
        self.assertEqual(rows[-1]['citation']['article'], '第一条')
        self.assertEqual(self.store.search('测试法规', as_of='2026-09-28'), [])

    def test_provenance_roundtrip_and_pdf_page_intersection(self):
        self.assertTrue(callable(getattr(self.store, 'set_provenance', None)), '缺少独立来源字段保存')
        version = self.add()
        text = self.store.detail(version)['text']
        second = text.index('第二条')
        metadata = {'publisher':'测试机关', 'original_url':'https://example.org/original.pdf',
                    'original_sha256':'a'*64, 'source_format':'pdf', 'document_number':None,
                    'source_dates':{'effective_from':'2026-11-01'},
                    'pages':[{'page':1,'start':0,'end':second-2},
                             {'page':2,'start':second,'end':len(text)}]}
        self.store.set_provenance(version, metadata)
        self.store.set_provenance(version, metadata)
        row = legal_mcp.get_law_article(version, '第二条')
        self.assertEqual(row['citation']['pages'], [2])
        self.assertEqual(row['citation']['original_url'], metadata['original_url'])
        self.assertEqual(row['citation']['source_dates']['effective_from'], '2026-11-01')
        self.assertIsNone(row['citation']['effective_from'])
        self.assertEqual(row['citation']['text_sha256'], hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(legal_mcp.get_law_fragment(version, offset=0, length=3)['citation']['pages'], [1])
        empty=legal_mcp.get_law_article(version,'第一条',offset=100)
        self.assertEqual(empty['text'],'')
        self.assertEqual(empty['citation']['pages'],[])
        from legal_citations import citation_for
        self.assertEqual(citation_for(self.store.detail(version),3,3)['pages'],[])
        with self.assertRaises(ValueError):
            self.store.set_provenance(version, {**metadata, 'publisher':'另一机关'})

    def test_invalid_page_metadata_cannot_be_saved(self):
        self.assertTrue(callable(getattr(self.store, 'set_provenance', None)), '缺少独立来源字段保存')
        version = self.add()
        for pages in ([{'page':1,'start':-1,'end':5}], [{'page':1,'start':0,'end':9999}],
                      [{'page':1,'start':0,'end':10},{'page':2,'start':8,'end':15}]):
            with self.assertRaises(ValueError):
                self.store.set_provenance(version, {'pages':pages})


if __name__ == '__main__':
    unittest.main()
