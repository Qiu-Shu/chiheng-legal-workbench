import unittest
from jilin_sources import extract_rule


class RuleLayoutTests(unittest.TestCase):
    title = '吉林省测试规定'

    def page(self, body, custom=True):
        wrapper = '<div class="Custom_UnionStyle">' if custom else '<div style="text-align:left;">'
        return ('<div id="zoom">'+wrapper+body+'</div></div>'
                '<div class="rul_note">吉林省人民政府发布</div><footer>外部导航</footer>').encode()

    def test_visible_div_paragraphs_preserve_order_and_do_not_duplicate(self):
        body='<div>吉林省测试规定</div><div>吉林省人民政府令第1号公布</div><div>第一条　<font>正文甲。</font></div><div><div>第二条　正文乙。</div><div>补充段落。</div></div>'
        expected='吉林省测试规定\n\n吉林省人民政府令第1号公布\n\n第一条　正文甲。\n\n第二条　正文乙。\n\n补充段落。'
        for custom in (True,False):
            with self.subTest(custom=custom):
                self.assertEqual(extract_rule(self.page(body,custom),self.title),expected)

    def test_fallback_rejects_zoom_text_and_tails_outside_wrapper(self):
        core='<div style="text-align:left;"><div>吉林省测试规定</div><div>吉林省人民政府令第1号公布</div><div>第一条 正文。</div></div>'
        for content in ('前言'+core,core+'附则',core+'<div style="display:none"></div>附则'):
            page=('<div id="zoom">'+content+'</div><div class="rul_note">吉林省人民政府发布</div>').encode()
            with self.subTest(content=content),self.assertRaises(ValueError):extract_rule(page,self.title)

    def test_nested_structured_headings_are_rejected_not_duplicated(self):
        body='<div class="DOCTITLE">吉林省测试规定</div><div class="DocAbstract">吉林省人民政府令第1号公布</div><div>第一条 正文。</div>'
        for custom in (False,True):
            with self.subTest(custom=custom),self.assertRaises(ValueError):extract_rule(self.page(body,custom),self.title)

    def test_unselected_wrapper_text_is_not_silently_lost(self):
        body='<div>吉林省测试规定</div><div>吉林省人民政府令第1号公布</div><div>前缀不能丢<div>第一条　正文。</div>尾部不能丢</div>'
        with self.assertRaises(ValueError):extract_rule(self.page(body),self.title)

    def test_multiple_fallback_containers_are_rejected(self):
        body=('<div id="zoom"><div style="text-align:left;"><div>吉林省测试规定</div>'
              '<div>吉林省人民政府令第1号公布</div></div><div>unexpected</div></div>'
              '<div class="rul_note">吉林省人民政府发布</div>').encode()
        with self.assertRaises(ValueError):extract_rule(body,self.title)

    def test_empty_hidden_sibling_is_ignored_but_content_is_not(self):
        prefix='<div id="zoom"><div style="text-align:left;"><div>吉林省测试规定</div><div>吉林省人民政府令第1号公布</div><div>第一条 正文。</div></div>'
        suffix='</div><div class="rul_note">吉林省人民政府发布</div>'
        self.assertEqual(extract_rule((prefix+'<div style="display:none">\n</div>'+suffix).encode(),self.title),
                         '吉林省测试规定\n\n吉林省人民政府令第1号公布\n\n第一条 正文。')
        for hidden in ('<div style="display:none">不能丢</div>','<div style="display:none"><img src="law.png"></div>'):
            with self.assertRaises(ValueError):extract_rule((prefix+hidden+suffix).encode(),self.title)

    def test_mixed_p_and_div_with_linebreak_preserves_separation(self):
        body='<div>吉林省测试规定</div><div>吉林省人民政府令第1号公布</div><p>第一条　甲<br>乙</p><div>第二条　丙</div>'
        self.assertEqual(extract_rule(self.page(body),self.title),
                         '吉林省测试规定\n\n吉林省人民政府令第1号公布\n\n第一条　甲\n乙\n\n第二条　丙')

    def test_hidden_or_nontext_body_is_rejected_not_silently_omitted(self):
        for obj in ('<img src="x">','<svg><text>正文</text></svg>',
                    '<div style="display: none">隐藏正文</div>','<span hidden>隐藏正文</span>'):
            body='<p>吉林省测试规定</p><p>吉林省人民政府令第1号公布</p><p>第一条　正文。'+obj+'</p>'
            with self.subTest(obj=obj),self.assertRaises(ValueError):
                extract_rule(self.page(body),self.title)
