import hashlib
import tempfile
import unittest
from pathlib import Path

import legal_mcp
from legal_store import LegalStore


class OfficialArticleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_db = legal_mcp.DB
        legal_mcp.DB = Path(self.tmp.name) / 'law.sqlite3'
        self.store = LegalStore(legal_mcp.DB)

    def tearDown(self):
        self.store.close()
        legal_mcp.DB = self.original_db
        self.tmp.cleanup()

    def add(self, text):
        return self.store.add(law_id='test', title='测试原件', text=text,
                              source_url='https://example.org/law', locator='正文', region='CN')

    def retrieve(self, version, article, **kwargs):
        self.assertTrue(callable(getattr(legal_mcp, 'get_law_article', None)),
                        '缺少原件按条号读取接口')
        return legal_mcp.get_law_article(version, article, **kwargs)

    def test_zero_suffix_and_exact_offsets(self):
        text = '标题\n第一章 总则\n\n第一百零一条　法人。\n第二款。\n\n第一百〇二条 组织。\n\n第一百〇二条之一 补充。\n'
        version = self.add(text)
        for label in ('第一百零一条', '第一百〇二条', '第一百〇二条之一'):
            row = self.retrieve(version, label)
            self.assertTrue(row['found'])
            self.assertEqual(row['text'], text[row['start']:row['end']])
            self.assertEqual(row['article_sha256'], hashlib.sha256(row['text'].encode()).hexdigest())
            self.assertEqual(row['review_state'], 'quarantine')
            self.assertFalse(row['legal_completeness_reviewed'])
        self.assertEqual(self.store.health()['published'], 0)

    def test_chapter_does_not_leak_into_previous_article(self):
        text = '第一条 内容。\n\n第二章 特别规定\n\n第二条 内容二。'
        version = self.add(text)
        self.assertEqual(self.retrieve(version, '第一条')['text'], '第一条 内容。')

    def test_inline_reference_is_not_heading(self):
        version = self.add('第一条 依照第二条 处理。\n继续规定。\n第二条 另一条。')
        row = self.retrieve(version, '第一条')
        self.assertEqual(row['article_count'], 2)
        self.assertIn('继续规定。', row['text'])

    def test_article_body_without_separator_is_not_merged(self):
        version = self.add('第一条内容中引用第二条。\n第二条其他内容。')
        row = self.retrieve(version, '第二条')
        self.assertTrue(row['found'])
        self.assertEqual(row['text'], '第二条其他内容。')
        self.assertEqual(row['article_count'], 2)
        suffix = self.add('第一条内容。\n第一条之一补充。')
        self.assertTrue(self.retrieve(suffix, '第一条之一')['found'])

    def test_space_inside_article_label_preserves_raw_text(self):
        version = self.add('第一条 内容。\n第二　条内容二。')
        row = self.retrieve(version, '第二条')
        self.assertTrue(row['found'])
        self.assertEqual(row['text'], '第二　条内容二。')

    def test_structural_heading_with_unassigned_prose_is_rejected(self):
        version = self.add('第一条 原文。\n第二章 引述或附件\n这段正文不能悄悄丢掉。\n第二条 其他。')
        with self.assertRaisesRegex(ValueError, '未归属正文'):
            self.retrieve(version, '第一条')

    def test_duplicate_toc_labels_are_rejected(self):
        version = self.add('目录\n第一条 目的\n第二条 范围\n正文\n第一条 真实内容。\n第二条 真实范围。')
        with self.assertRaisesRegex(ValueError, '重复'):
            self.retrieve(version, '第一条')

    def test_empty_heading_is_rejected(self):
        version = self.add('第一条\n\n第二条 其他。')
        with self.assertRaisesRegex(ValueError, '空正文'):
            self.retrieve(version, '第一条')

    def test_unknown_article_does_not_claim_nonexistence(self):
        version = self.add('第一条 内容。')
        row = self.retrieve(version, '第二条')
        self.assertFalse(row['found'])
        self.assertFalse(row['coverage_complete'])
        self.assertIn('索引', row['notice'])

    def test_missing_version(self):
        self.assertFalse(self.retrieve('missing', '第一条')['found'])

    def test_pagination_round_trip_and_limits(self):
        version = self.add('第一条 很长的内容。\n多行正文。')
        whole = self.retrieve(version, '第一条')
        first = self.retrieve(version, '第一条', length=6)
        rest = self.retrieve(version, '第一条', offset=6)
        self.assertTrue(first['truncated'])
        self.assertEqual(first['text'] + rest['text'], whole['text'])
        for kwargs in ({'offset': -1}, {'length': 0}, {'length': 10001}):
            with self.assertRaises(ValueError):
                self.retrieve(version, '第一条', **kwargs)

    def test_no_heading_is_an_explicit_error(self):
        version = self.add('该网页只有目录链接，并没有法规正文。')
        with self.assertRaisesRegex(ValueError, '条号'):
            self.retrieve(version, '第一条')


if __name__ == '__main__':
    unittest.main()
