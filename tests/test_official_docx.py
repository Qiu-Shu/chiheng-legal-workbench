import importlib.util
import io
import unittest
from zipfile import ZipFile


def document(body, styles=None):
    stream = io.BytesIO()
    with ZipFile(stream, 'w') as archive:
        archive.writestr('word/document.xml',
                         '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                         '<w:body>' + body + '</w:body></w:document>')
        if styles is not None:
            archive.writestr('word/styles.xml', styles)
    return stream.getvalue()


class OfficialDocxTests(unittest.TestCase):
    def test_wrapped_title_after_announcement_preserves_every_paragraph(self):
        payload = document('<w:p><w:r><w:t>最高人民法院公告</w:t></w:r></w:p>'
                           '<w:p><w:r><w:t>公告内容。</w:t></w:r></w:p>'
                           '<w:p><w:r><w:t>最高人民法院</w:t></w:r></w:p>'
                           '<w:p><w:r><w:t>测试解释</w:t></w:r></w:p>'
                           '<w:p><w:r><w:t>第一条 内容。</w:t></w:r></w:p>')
        text, facts = self.module().extract_docx(payload, '最高人民法院测试解释')
        self.assertIn('公告内容。\n\n最高人民法院\n\n测试解释', text)
        self.assertEqual(facts['title_paragraph_range'], [2, 4])

    def test_title_found_only_in_article_is_rejected(self):
        payload = document('<w:p><w:r><w:t>第一条 内容。</w:t></w:r></w:p>'
                           '<w:p><w:r><w:t>测试法律</w:t></w:r></w:p>')
        with self.assertRaisesRegex(ValueError, '标题'):
            self.module().extract_docx(payload, '测试法律')

    def test_empty_bookmark_markers_not_body_content(self):
        payload = document('<w:bookmarkStart w:id="1" w:name="x"/>'
                           '<w:p><w:r><w:t>测试法律</w:t></w:r></w:p><w:bookmarkEnd w:id="1"/>')
        self.assertEqual(self.module().extract_docx(payload, '测试法律')[0], '测试法律\n')
        with self.assertRaises(ValueError):
            self.module().extract_docx(document('<w:bookmarkEnd>丢失正文</w:bookmarkEnd>'), '测试法律')

    def test_missing_catalog_has_explicit_lower_validation_scope(self):
        module = self.module()
        self.assertEqual(module.article_labels(None), [])
        self.assertEqual(module.normalize_headings('第一条 内容。', None), ('第一条 内容。', []))
        report = module.check_articles('第一条 内容。', [], allow_missing_catalog=True)
        self.assertFalse(report['official_labels_match'])
        self.assertEqual(report['catalog_status'], 'missing')
        with self.assertRaises(ValueError):
            module.check_articles('第一条 内容。', ['第一条', '第二条'], allow_missing_catalog=True)

    def test_missing_catalog_rejects_numbering_gaps_and_nonfirst_start(self):
        for text in ('第一条 内容。\n第三条 内容。', '第二条 内容。',
                     '第一条 内容。\n第一条之一 补充。'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, '连续条号'):
                self.module().check_articles(text, [], allow_missing_catalog=True)

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('official_docx'), '缺少受检DOCX抽取模块')
        import official_docx
        return official_docx

    def test_paragraph_tab_break_and_title(self):
        payload = document('<w:p><w:r><w:t>测试法律</w:t></w:r></w:p><w:p/>'
                           '<w:p><w:r><w:t>第一条</w:t><w:tab/><w:t>内容。</w:t>'
                           '<w:br/><w:t>下一行。</w:t></w:r></w:p>')
        text, facts = self.module().extract_docx(payload, '测试法律')
        self.assertEqual(text, '测试法律\n\n\n\n第一条\t内容。\n下一行。\n')
        self.assertEqual(facts['paragraphs'], 3)

    def test_wrong_title_rejected(self):
        payload = document('<w:p><w:r><w:t>别的法律</w:t></w:r></w:p>')
        with self.assertRaisesRegex(ValueError, '标题'):
            self.module().extract_docx(payload, '测试法律')

    def test_explicit_zero_numbering_is_removal_not_generated_text(self):
        payload = document('<w:p><w:r><w:t>测试法律</w:t></w:r></w:p>'
                           '<w:p><w:pPr><w:numPr><w:numId w:val="0"/></w:numPr></w:pPr></w:p>')
        text, facts = self.module().extract_docx(payload, '测试法律')
        self.assertEqual(text, '测试法律\n\n\n')
        self.assertEqual(facts['disabled_numbering_properties'], 1)

    def test_live_automatic_numbering_is_rejected(self):
        payload = document('<w:p><w:r><w:t>测试法律</w:t></w:r></w:p>'
                           '<w:p><w:pPr><w:numPr><w:numId w:val="1"/></w:numPr></w:pPr></w:p>')
        with self.assertRaisesRegex(ValueError, '不支持'):
            self.module().extract_docx(payload, '测试法律')

    def test_inline_math_is_rejected_not_dropped(self):
        payload = document('<w:p><w:r><w:t>测试法律</w:t></w:r></w:p><w:p>'
                           '<w:r><w:t>第一条 金额为</w:t></w:r>'
                           '<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
                           '<m:r><m:t>100</m:t></m:r></m:oMath><w:r><w:t>元。</w:t></w:r></w:p>')
        with self.assertRaisesRegex(ValueError, '不支持'):
            self.module().extract_docx(payload, '测试法律')

    def test_style_numbering_is_rejected(self):
        payload = document('<w:p><w:r><w:t>测试法律</w:t></w:r></w:p>'
                           '<w:p><w:pPr><w:pStyle w:val="List"/></w:pPr><w:r><w:t>内容。</w:t></w:r></w:p>',
                           '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                           '<w:style w:styleId="List"><w:pPr><w:numPr><w:numId w:val="1"/>'
                           '</w:numPr></w:pPr></w:style></w:styles>')
        with self.assertRaisesRegex(ValueError, '不支持'):
            self.module().extract_docx(payload, '测试法律')

    def test_explicit_zero_style_numbering_is_not_generated_text(self):
        styles = ('<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                  '<w:style w:styleId="List"><w:pPr><w:numPr><w:ilvl w:val="0"/>'
                  '<w:numId w:val="0"/></w:numPr></w:pPr></w:style></w:styles>')
        payload = document('<w:p><w:pPr><w:pStyle w:val="List"/></w:pPr>'
                           '<w:r><w:t>测试法律</w:t></w:r></w:p>', styles)
        text, facts = self.module().extract_docx(payload, '测试法律')
        self.assertEqual(text, '测试法律\n')
        self.assertEqual(facts['disabled_style_numbering_properties'], 1)

    def test_complex_content_not_silently_lost(self):
        for tag in ('tbl', 'drawing', 'pict', 'object', 'altChunk', 'footnoteReference',
                    'endnoteReference', 'sym', 'ins', 'del', 'numPr'):
            with self.subTest(tag=tag):
                payload = document('<w:p><w:r><w:t>测试法律</w:t></w:r></w:p>' + f'<w:{tag}/>')
                with self.assertRaisesRegex(ValueError, '不支持'):
                    self.module().extract_docx(payload, '测试法律')

    def test_unknown_body_wrapper_rejected(self):
        payload = document('<w:p><w:r><w:t>测试法律</w:t></w:r></w:p><w:sdt/>')
        with self.assertRaisesRegex(ValueError, '不支持'):
            self.module().extract_docx(payload, '测试法律')

    def test_exact_official_labels_and_body_spans(self):
        text = '测试法律\n第一章 总则\n第一条 内容。\n\n第二章 后续\n第二条 其他。\n'
        report = self.module().check_articles(text, ['第一条', '第二条'])
        self.assertEqual(report['article_count'], 2)
        self.assertTrue(report['official_labels_match'])
        self.assertEqual(report['unassigned_body_content'], 0)
        for row in report['articles']:
            self.assertTrue(text[row['start']:row['end']].startswith(row['article']))

    def test_missing_official_article_rejected(self):
        with self.assertRaisesRegex(ValueError, '官方条号'):
            self.module().check_articles('第一条 内容。', ['第一条', '第二条'])

    def test_empty_official_tree_rejected(self):
        with self.assertRaisesRegex(ValueError, '官方条号'):
            self.module().check_articles('第一条 内容。', [])

    def test_tree_extracts_articles_not_chapters(self):
        tree = {'title': '法规', 'children': [
            {'title': '第一章 总则', 'children': [{'title': '第一条 目的', 'children': []}]},
            {'title': '第一百零一条之一', 'children': []}]}
        self.assertEqual(self.module().article_labels(tree), ['第一条', '第一百零一条之一'])

    def test_only_officially_matching_wrapped_heading_is_normalized(self):
        module = self.module()
        self.assertTrue(callable(getattr(module, 'normalize_headings', None)), '缺少有官方目录约束的标题换行处理')
        original = '第一条 内容。\n\n第二章　犯罪案件\n特别程序\n\n第二条 其他。\n'
        tree = {'title': '第二章 犯罪案件特别程序', 'children': []}
        normalized, changes = module.normalize_headings(original, tree)
        self.assertEqual(normalized, original.replace('案件\n特别', '案件 特别'))
        self.assertEqual(len(normalized), len(original))
        self.assertEqual(changes[0]['original'], '第二章　犯罪案件\n特别程序')
        self.assertEqual(module.check_articles(normalized, ['第一条', '第二条'])['article_count'], 2)
        unchanged, changes = module.normalize_headings(original, {'title': '第二章 不同标题'})
        self.assertEqual(unchanged, original)
        self.assertEqual(changes, [])


if __name__ == '__main__':
    unittest.main()
