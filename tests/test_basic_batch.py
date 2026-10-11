import importlib.util
import tempfile
import unittest
from pathlib import Path
from legal_store import LegalStore


class BasicBatchTests(unittest.TestCase):
    def test_source_card_dates_are_observed_not_approval(self):
        module=self.module()
        self.assertTrue(callable(getattr(module,'source_metadata',None)), '缺少基础法来源字段映射')
        row={'official_metadata':{'zdjgName':'测试机关','gbrq':'2026-09-01','sxrq':'2026-11-01'},
             'object_url_without_signature':'https://example.org/law.docx','docx_sha256':'a'*64}
        facts=module.source_metadata(row)
        self.assertEqual(facts['source_dates']['effective_from'],'2026-11-01')
        self.assertNotIn('effective_from',facts)
        self.assertEqual(facts['publisher'],'测试机关')
        self.assertEqual(facts['original_sha256'],'a'*64)
        self.assertIsNone(facts['document_number'])

    def test_legacy_doc_url_requires_explicit_opt_in(self):
        path = 'prod/20201229/test.doc'
        url = 'https://flkoss.obs-bj2.cucloud.cn/' + path
        with self.assertRaises(ValueError):
            self.module().public_object_url(url, path)
        self.assertEqual(self.module().public_object_url(url, path, allow_legacy_doc=True), url)
        with self.assertRaises(ValueError):
            self.module().public_object_url('https://evil.example/' + path, path, allow_legacy_doc=True)

    def test_unnumbered_reply_is_not_a_generic_failed_article_fallback(self):
        module = self.module()
        self.assertTrue(callable(getattr(module, 'check_document', None)))
        reply_id = 'ff808181927f1276019448a29dca7d34'
        report = module.check_document('批复\n河南省高级人民法院：\n正文。\n此复。', None, reply_id)
        self.assertEqual(report['structure'], 'unnumbered_document')
        self.assertEqual(report['article_count'], 0)
        self.assertFalse(report['legal_completeness_reviewed'])
        for text, id in [('第一条 正文。', reply_id), ('批复正文。', 'unknown')]:
            with self.assertRaises(ValueError):
                module.check_document(text, None, id)
    def test_named_batches_are_separate_bounded_and_no_arbitrary_output_path(self):
        module = self.module()
        self.assertTrue(callable(getattr(module, 'batch_targets', None)), '缺少固定配套批次选择')
        basic = module.batch_targets('basic-laws')
        supporting = module.batch_targets('supporting-rules')
        self.assertEqual(basic, module.TARGETS)
        self.assertEqual(len(supporting), 14)
        ids = [law_id for title, law_id in supporting]
        self.assertEqual(len(set(ids)), len(ids))
        self.assertFalse(set(ids) & {law_id for title, law_id in basic})
        with self.assertRaises(ValueError):
            module.batch_targets('../other-report')

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('scripts.ingest_basic_laws'), '缺少受限批次脚本')
        from scripts import ingest_basic_laws
        return ingest_basic_laws

    def test_reuse_identical_artifact_never_overwrite_different(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'original.docx'
            module = self.module()
            module.keep_original(target, b'original')
            module.keep_original(target, b'original')
            with self.assertRaises(ValueError):
                module.keep_original(target, b'changed')
            self.assertEqual(target.read_bytes(), b'original')

    def test_only_expected_https_object_and_path(self):
        module = self.module()
        path = 'prod/20230901/abc.docx'
        self.assertEqual(module.public_object_url('https://flkoss.obs-bj2.cucloud.cn/' + path + '?signature=secret', path),
                         'https://flkoss.obs-bj2.cucloud.cn/' + path)
        for url in ('http://flkoss.obs-bj2.cucloud.cn/' + path,
                    'https://evil.example/' + path,
                    'https://user:password@flkoss.obs-bj2.cucloud.cn/' + path,
                    'https://flkoss.obs-bj2.cucloud.cn/other.docx',
                    'https://flkoss.obs-bj2.cucloud.cn:444/' + path):
            with self.assertRaises(ValueError):
                module.public_object_url(url, path)

    def test_bad_port_never_exposes_value(self):
        with self.assertRaises(ValueError) as raised:
            self.module().public_object_url('https://flkoss.obs-bj2.cucloud.cn:secret-signature/prod/a.docx', 'prod/a.docx')
        self.assertNotIn('secret-signature', str(raised.exception))

    def test_reused_published_version_is_reported_without_revocation(self):
        module = self.module()
        self.assertTrue(callable(getattr(module, 'storage_result', None)), '缺少按实际状态报告的处理')
        with tempfile.TemporaryDirectory() as tmp:
            store = LegalStore(Path(tmp) / 'law.sqlite3')
            try:
                args = dict(law_id='test', title='测试法规', text='第一条 内容。',
                            source_url='https://example.org/law', locator='正文', region='CN')
                version = store.add(**args)
                self.assertEqual(module.storage_result(store.detail(version))['status'], 'ingested_quarantine')
                store.approve(version, reviewer='test-human', effective_from='2024-01-01')
                self.assertEqual(store.add(**args), version)
                result = module.storage_result(store.detail(version))
                self.assertEqual(result['status'], 'reused_published')
                self.assertEqual(result['review_state'], 'published')
                self.assertEqual(store.detail(version)['reviewer'], 'test-human')
            finally:
                store.close()
