import hashlib
import importlib.util
import subprocess
import unittest
from local_settings import resolve_pdf_python


RUNTIME = resolve_pdf_python()


def pdf(pages=None, extra='', before=''):
    source = f'''
import io, sys
from reportlab.pdfgen import canvas
s = io.BytesIO()
c = canvas.Canvas(s, pagesize=(600, 800))
for number, lines in enumerate({pages or [['Test Law', 'Article 1. Content.']]!r}, 1):
    {before or 'pass'}
    c.setFillColorRGB(0, 0, 0)
    for row, line in enumerate(lines):
        c.drawString(60, 720 - row * 24, line)
    {extra or 'pass'}
    c.showPage()
c.save()
sys.stdout.buffer.write(s.getvalue())
'''
    return subprocess.run([str(RUNTIME), '-c', source], check=True, capture_output=True).stdout


class OfficialPdfTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('official_pdf'), '缺少受检PDF抽取模块')
        import official_pdf
        return official_pdf

    def test_text_pages_preserve_offsets_raw_text_and_hashes(self):
        payload = pdf([['Test Law', 'Article 1. Content.'], ['Article 2. More.']])
        text, report = self.module().extract_pdf(payload, 'Test Law')
        self.assertEqual(text, 'Test Law\nArticle 1. Content.\n\nArticle 2. More.\n')
        self.assertEqual(report['page_count'], 2)
        self.assertEqual(report['source_sha256'], hashlib.sha256(payload).hexdigest())
        self.assertEqual(report['text_sha256'], hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(set(report['parsers']), {'pypdf', 'pdfplumber'})
        self.assertFalse(report['legal_completeness_reviewed'])
        self.assertNotIn('bounds',report,'无例外时保持既有提取报告兼容')
        for row in report['pages']:
            self.assertEqual(text[row['start']:row['end']], row['body_text'])
            self.assertEqual(row['body_sha256'], hashlib.sha256(row['body_text'].encode()).hexdigest())
            for parser, raw in row['raw_text'].items():
                self.assertEqual(row['raw_sha256'][parser], hashlib.sha256(raw.encode()).hexdigest())
                self.assertIn('parser_body_sha256', row, '双工具正文hash应留存')
                self.assertEqual(row['parser_body_sha256'][parser],
                                 hashlib.sha256(row['parser_body_text'][parser].encode()).hexdigest())

    def test_title_whitespace_matches_but_wrong_title_fails(self):
        payload = pdf()
        self.module().extract_pdf(payload, 'TestLaw')
        with self.assertRaisesRegex(ValueError, '标题'):
            self.module().extract_pdf(payload, 'Different Law')

    def test_nonpdf_and_corrupt_pdf_fail(self):
        for payload in (b'not a pdf', b'%PDF-1.4\ncorrupt'):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.module().extract_pdf(payload, 'Test Law')

    def test_blank_page_is_rejected(self):
        with self.assertRaisesRegex(ValueError, '文字'):
            self.module().extract_pdf(pdf([[]]), 'Test Law')

    def test_only_geometrically_confirmed_footer_is_removed(self):
        payload = pdf([['Test Law', '1', 'Article 1. Content.']], extra="c.drawCentredString(300, 30, str(number))")
        text, report = self.module().extract_pdf(payload, 'Test Law')
        self.assertIn('\n1\n', text)
        self.assertTrue(text.endswith('Content.\n'))
        self.assertEqual(report['pages'][0]['footer']['text'], '1')
        self.assertEqual(report['pages'][0]['footer']['removed_from']['pdfplumber'], 'suffix')
        self.assertGreater(report['pages'][0]['footer']['bbox'][1], 700)

    def test_body_terminal_number_is_preserved(self):
        text, report = self.module().extract_pdf(pdf([['Test Law', 'Article 1.', '1']]), 'Test Law')
        self.assertTrue(text.endswith('\n1\n'))
        self.assertIsNone(report['pages'][0]['footer'])

    def test_footer_drawn_first_can_move_between_parsers(self):
        payload = pdf(before="c.drawCentredString(300, 30, str(number))")
        text, report = self.module().extract_pdf(payload, 'Test Law')
        self.assertTrue(text.startswith('Test Law'))
        self.assertEqual(report['pages'][0]['footer']['removed_from'], {'pypdf': 'prefix', 'pdfplumber': 'suffix'})

    def test_visible_table_and_image_are_rejected(self):
        for extra in ("c.grid([60, 160, 260], [450, 480, 510])",
                      "c.drawInlineImage(__import__('PIL.Image', fromlist=['Image']).new('RGB', (4, 4)), 60, 400, 30, 30)"):
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, '不支持'):
                self.module().extract_pdf(pdf(extra=extra), 'Test Law')

    def test_white_background_allowed_but_later_white_cover_rejected(self):
        rectangle = 'c.setFillColorRGB(1, 1, 1); c.rect(50, 680, 400, 60, stroke=0, fill=1)'
        text, report = self.module().extract_pdf(pdf(before=rectangle), 'Test Law')
        self.assertIn('Article 1.', text)
        self.assertEqual(report['pages'][0]['white_background_rectangles'], 1)
        with self.assertRaisesRegex(ValueError, '覆盖'):
            self.module().extract_pdf(pdf(extra=rectangle), 'Test Law')

    def test_encrypted_document_rejected(self):
        payload = pdf()
        script = ('import io,sys; from pypdf import PdfReader,PdfWriter; '
                  'w=PdfWriter(clone_from=PdfReader(io.BytesIO(sys.stdin.buffer.read()))); '
                  "w.encrypt('secret'); out=io.BytesIO(); w.write(out); sys.stdout.buffer.write(out.getvalue())")
        encrypted = subprocess.run([str(RUNTIME), '-c', script], input=payload, capture_output=True, check=True).stdout
        with self.assertRaisesRegex(ValueError, '加密'):
            self.module().extract_pdf(encrypted, 'Test Law')

    def test_white_text_in_saved_graphics_state_is_rejected(self):
        for color in ('c.setFillGray(1)', 'c.setFillColorRGB(1, 1, 1)',
                      'c.setFillColorCMYK(0, 0, 0, 0)'):
            extra = (f'c.saveState(); {color}; '
                     "c.drawString(60, 400, 'INVISIBLE SECRET TEXT'); c.restoreState(); "
                     "c.drawString(60, 360, 'Visible text after Q')")
            with self.subTest(color=color), self.assertRaisesRegex(ValueError, '白色文字'):
                self.module().extract_pdf(pdf(extra=extra), 'Test Law')

    def test_restored_white_color_without_white_glyphs_is_allowed(self):
        extra = ('c.saveState(); c.setFillColorRGB(1, 1, 1); c.restoreState(); '
                 "c.drawString(60, 400, 'Visible text after Q')")
        text, _ = self.module().extract_pdf(pdf(extra=extra), 'Test Law')
        self.assertIn('Visible text after Q', text)

    def test_transparent_text_and_saved_alpha_states_are_rejected(self):
        for extra in (
                "c.setFillAlpha(0); c.drawString(60, 400, 'INVISIBLE SECRET TEXT')",
                "c.saveState(); c.setFillAlpha(0); c.drawString(60, 400, 'SECRET'); "
                "c.restoreState(); c.drawString(60, 360, 'Visible after Q')",
                "c.saveState(); c.setFillAlpha(.5); c.drawString(60, 400, 'Faint text'); c.restoreState()"):
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, 'ExtGState'):
                self.module().extract_pdf(pdf(extra=extra), 'Test Law')

    def test_clipped_glyphs_are_rejected(self):
        extra = ("p=c.beginPath(); p.rect(0, 0, 10, 10); c.clipPath(p, stroke=0); "
                 "c.drawString(60, 600, 'CLIPPED SECRET')")
        with self.assertRaisesRegex(ValueError, '可视|裁剪'):
            self.module().extract_pdf(pdf(extra=extra), 'Test Law')

    def test_confirmed_removed_footer_may_have_a_clipped_advance_box(self):
        extra=("c.saveState(); p=c.beginPath(); p.rect(290,20,12.6,30); c.clipPath(p,stroke=0); "
               "c.drawString(296,30,str(number)); c.restoreState()")
        try:text,report=self.module().extract_pdf(pdf(extra=extra),'Test Law')
        except ValueError as exc:self.fail(f'已从双工具正文删除的页脚不应阻止正文核对：{exc}')
        self.assertNotIn('\n1',text)
        self.assertEqual(report['bounds']['removed_footer_clip_exceptions'][0]['text'],'1')
        self.assertEqual(report['pages'][0]['footer']['removed_from'],{'pypdf':'suffix','pdfplumber':'suffix'})

    def test_footer_exception_does_not_allow_clipped_body_or_unconfirmed_footer(self):
        for content,y in (("'Article 2. HIDDEN.'",600),("'2'",30)):
            extra=(f"c.saveState(); p=c.beginPath(); p.rect(290,{y-10},12.6,30); c.clipPath(p,stroke=0); "
                   f"c.drawString(296,{y},{content}); c.restoreState()")
            with self.subTest(content=content),self.assertRaisesRegex(ValueError,'可视|裁剪'):
                self.module().extract_pdf(pdf(extra=extra),'Test Law')

    def test_confirmed_footer_cannot_exempt_body_with_the_same_digit_or_physical_overflow(self):
        cases=[("c.saveState(); p=c.beginPath(); p.rect(290,590,12.6,30); c.clipPath(p,stroke=0); "
                "c.drawString(296,600,'1'); c.restoreState(); c.drawString(296,30,'1')"),
               "c.drawString(296,1,'1')"]
        for extra in cases:
            with self.subTest(extra=extra),self.assertRaisesRegex(ValueError,'可视|裁剪|双工具'):
                self.module().extract_pdf(pdf(extra=extra),'Test Law')

    def test_footer_clip_exceptions_are_scoped_to_their_page(self):
        extra=("c.saveState(); p=c.beginPath(); p.rect(290,20,12.6,30); c.clipPath(p,stroke=0); "
               "c.drawString(296,30,str(number)); c.restoreState()")
        _,report=self.module().extract_pdf(pdf([['Test Law','Article 1. Content.'],['Article 2. More.']],extra=extra),'Test Law')
        self.assertEqual([(x['page'],x['text']) for x in report['bounds']['removed_footer_clip_exceptions']],[(1,'1'),(2,'2')])

    def test_rectangular_clip_restored_with_q_allows_visible_text(self):
        extra = ('c.saveState(); c.translate(20, 10); p=c.beginPath(); '
                 'p.rect(30, 350, 300, 100); c.clipPath(p, stroke=0); '
                 "c.drawString(40, 390, 'Visible inside clip'); c.restoreState(); "
                 "c.drawString(60, 300, 'Visible outside restored clip')")
        text, _ = self.module().extract_pdf(pdf(extra=extra), 'Test Law')
        self.assertIn('Visible inside clip', text)
        self.assertIn('Visible outside restored clip', text)

    def test_restoring_ctm_with_pending_path_is_rejected(self):
        extra = ("c._code.append('q 1 0 0 1 6000 0 cm 0 0 600 800 re Q W n'); "
                 "c.drawString(60, 600, 'Article 2. INVISIBLE TEXT.')")
        with self.assertRaisesRegex(ValueError, '裁剪路径'):
            self.module().extract_pdf(pdf(extra=extra), 'Test Law')

    def test_glyphs_outside_media_box_are_rejected(self):
        for x, y in ((60, -20), (610, 400), (-20, 400), (60, 810)):
            # Either early parser disagreement or the glyph-bounds check rejects it.
            with self.subTest(x=x, y=y), self.assertRaisesRegex(ValueError, '可视|裁剪|双工具'):
                self.module().extract_pdf(pdf(extra=f"c.drawString({x}, {y}, 'OUTSIDE')"), 'Test Law')

    def test_exact_neutral_graphics_state_is_allowed_but_changes_are_rejected(self):
        script='''
import io,sys
from pypdf import PdfReader,PdfWriter
from pypdf.generic import DictionaryObject,NameObject,BooleanObject,NumberObject,DecodedStreamObject
w=PdfWriter(clone_from=PdfReader(io.BytesIO(sys.stdin.buffer.read())))
p=w.pages[0]
g=DictionaryObject({NameObject('/Type'):NameObject('/ExtGState'),NameObject('/AIS'):BooleanObject(False),NameObject('/BM'):NameObject('/Normal'),NameObject('/CA'):NumberObject(1),NameObject('/ca'):NumberObject(1)})
if sys.argv[1]=='alpha':g[NameObject('/ca')]=NumberObject(0)
if sys.argv[1]=='mask':g[NameObject('/SMask')]=NameObject('/None')
if sys.argv[1]=='blend':g[NameObject('/BM')]=NameObject('/Multiply')
p['/Resources'][NameObject('/ExtGState')]=DictionaryObject({NameObject('/Neutral'):g})
s=DecodedStreamObject();s.set_data(b'/Neutral gs\\n'+p.get_contents().get_data());p[NameObject('/Contents')]=w._add_object(s)
out=io.BytesIO();w.write(out);sys.stdout.buffer.write(out.getvalue())
'''
        for kind in ('neutral','alpha','mask','blend'):
            payload=subprocess.run([str(RUNTIME),'-c',script,kind],input=pdf(),capture_output=True,check=True).stdout
            if kind=='neutral':
                try:text,_=self.module().extract_pdf(payload,'Test Law')
                except ValueError as exc:self.fail(f'精确不透明正常混合状态应可验证：{exc}')
                self.assertIn('Content.',text)
            else:
                with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'ExtGState'):
                    self.module().extract_pdf(payload,'Test Law')

    def test_crop_box_and_nonzero_media_origin_are_respected(self):
        script = '''
import io,sys
from pypdf import PdfReader,PdfWriter
from pypdf.generic import RectangleObject
w=PdfWriter(clone_from=PdfReader(io.BytesIO(sys.stdin.buffer.read())))
p=w.pages[0]
p.mediabox=RectangleObject([20,20,620,820])
p.cropbox=RectangleObject([20,20,int(sys.argv[1]),820])
out=io.BytesIO();w.write(out);sys.stdout.buffer.write(out.getvalue())
'''
        payload = pdf(extra="c.drawString(400, 400, 'CROP CONTENT')")
        for edge in (300, 620):
            changed = subprocess.run([str(RUNTIME), '-c', script, str(edge)], input=payload,
                                     capture_output=True, check=True).stdout
            if edge == 300:
                with self.assertRaisesRegex(ValueError, '可视|裁剪'):
                    self.module().extract_pdf(changed, 'Test Law')
            else:
                text, _ = self.module().extract_pdf(changed, 'Test Law')
                self.assertIn('CROP CONTENT', text)

    def test_content_difference_rejected(self):
        self.module()
        script = '''
import sys
from unittest.mock import patch
from pypdf._page import PageObject
from official_pdf import _extract_local
original = PageObject.extract_text
def changed(self, *args, **kwargs):
    return original(self, *args, **kwargs).replace('Content.', 'Changed.')
with patch.object(PageObject, 'extract_text', changed):
    try:
        _extract_local(sys.stdin.buffer.read(), 'Test Law')
    except ValueError as exc:
        assert '一致' in str(exc), str(exc)
    else:
        raise AssertionError('parser disagreement accepted')
'''
        result = subprocess.run([str(RUNTIME), '-c', script], input=pdf(), capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_size_limit_rejected(self):
        with self.assertRaisesRegex(ValueError, '10MB'):
            self.module().extract_pdf(b'%PDF-' + b'0' * 10_000_000, 'Test Law')

    def test_each_parser_has_its_own_total_text_limit(self):
        self.module()
        script = '''
import sys
from unittest.mock import patch
from pypdf._page import PageObject
import official_pdf
original = PageObject.extract_text
def padded(self, *args, **kwargs):
    return original(self, *args, **kwargs) + ' ' * 12
with patch.object(PageObject, 'extract_text', padded), patch.object(official_pdf, 'MAX_TEXT', 35):
    try:
        official_pdf._extract_local(sys.stdin.buffer.read(), 'Test Law')
    except ValueError as exc:
        assert '文字超过' in str(exc), str(exc)
    else:
        raise AssertionError('individual parser text limit not enforced')
'''
        result = subprocess.run([str(RUNTIME), '-c', script], input=pdf(), capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_page_limit_rejected(self):
        with self.assertRaisesRegex(ValueError, '100页'):
            self.module().extract_pdf(pdf([['Test Law']] * 101), 'Test Law')


if __name__ == '__main__':
    unittest.main()
