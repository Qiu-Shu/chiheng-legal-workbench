import importlib.util
import subprocess
import unittest
from pathlib import Path


class LegacyDocTests(unittest.TestCase):
    def test_real_source_does_not_promote_page_fields(self):
        from official_docx import extract_docx
        source = Path(__file__).resolve().parents[1] / 'data/official-basic-laws/ff808181799def980179b1ab569c1b33/9a29d1fdee3e037dad0704d575efbe1e4af5c05c8fa33989f4d5f61eacdd2b11/original.doc'
        if not source.exists():
            self.skipTest('固定官方原件未随源代码包分发')
        docx, direct = self.converter()(source.read_bytes())
        text, _ = extract_docx(docx, '最高人民法院关于适用《中华人民共和国民事诉讼法》审判监督程序若干问题的解释')
        self.assertNotIn('PAGE', text)
        self.assertNotIn('PAGE', direct)
        self.assertTrue(text.rstrip().endswith('本解释未作规定的，按照以前的规定执行。'))

    def converter(self):
        self.assertIsNotNone(importlib.util.find_spec('legacy_doc'), '缺少有原件检查的旧DOC转换')
        from legacy_doc import convert_legacy_doc
        return convert_legacy_doc

    def test_not_doc_rejected_before_conversion(self):
        with self.assertRaises(ValueError):
            self.converter()(b'<html>not Word</html>')

    @unittest.skipUnless(Path('/usr/bin/textutil').exists(), 'macOS转换器不可用')
    def test_real_native_conversion_retains_plain_text(self):
        from official_docx import extract_docx
        original = '测试法律\n第一条 正文。\n第二条 其他。\n'
        doc = subprocess.run(['/usr/bin/textutil', '-convert', 'doc', '-format', 'txt',
                              '-stdin', '-stdout'], input=original.encode(), capture_output=True,
                             check=True, timeout=30).stdout
        docx, direct = self.converter()(doc)
        extracted, facts = extract_docx(docx, '测试法律')
        self.assertEqual(''.join(extracted.split()), ''.join(original.split()))
        self.assertEqual(''.join(direct.split()), ''.join(original.split()))
