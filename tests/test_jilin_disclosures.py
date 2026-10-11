import copy
import portable_lock as fcntl
import hashlib
import importlib
import json
import re
import tempfile
import unittest
from pathlib import Path
from lxml import html
from scrapling.engines.toolbelt.custom import Response
from legal_citations import citation_for
from legal_store import LegalStore
from jilin_sources import PublicReader, allowed_url

ROOT = Path(__file__).resolve().parents[1]


class DisclosureTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('jilin_disclosures'), 'disclosure parser is not implemented')
        return importlib.import_module('jilin_disclosures')

    def source(self, index=0):
        self.module()
        return json.loads((ROOT/'config/jilin-disclosures.json').read_text())['sources'][index]

    def original(self, index=0):
        digest = ('2411277231b5f83ade95998ed3001841b18d891b2d279935c4400d238c6f3234',
                  '4da992b7c79e0febfa634c5bd5828f4b9bdad6245ad9fae485016338c19871db',
                  '5f344971c16e02cc0e2369d84909fe3f05a18cabd1a40d8569da34b6e6e965bf')[index]
        path = ROOT/'tests/fixtures/jilin-disclosures'/f'{digest}.html'
        self.assertTrue(path.is_file(), 'official HTML fixture must ship with source tests')
        payload = path.read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(), digest)
        return payload

    def changed(self, transform, index=0):
        tree = html.fromstring(self.original(index).decode('utf8'))
        transform(tree)
        return html.tostring(tree, encoding='utf8')

    def reader(self, payload):
        def fetch(url):
            return Response(url=url, content=b'' if url.endswith('/robots.txt') else payload,
                            status=404 if url.endswith('/robots.txt') else 200, reason='fixture',
                            cookies={}, headers={}, request_headers={})
        return PublicReader(fetch=fetch, delay=0)

    def test_fire_preserves_observed_date_conflict_in_citation(self):
        mod = self.module(); source = self.source()
        text, facts = mod.parse_disclosure(self.original(), source)
        self.assertIn('2026年8月25日', text)
        self.assertIn('（三十五）严肃责任追究', text)
        self.assertEqual(facts['source_dates']['metadata_created'], '2026-08-28')
        self.assertEqual(facts['source_dates']['body_signature'], '2026-08-25')
        self.assertTrue(facts['source_dates']['created_signature_discrepancy'])
        with tempfile.TemporaryDirectory() as tmp:
            store = LegalStore(Path(tmp)/'test.sqlite3')
            row = mod.ingest_disclosure(Path(tmp), source, self.reader(self.original()), store)
            detail = store.detail(row['version_id'])
            card = citation_for(detail, 0, 20)
            self.assertTrue(card['source_dates']['created_signature_discrepancy'])
            self.assertIsNone(card['effective_from'])
            self.assertEqual(card['review_state'], 'quarantine')
            self.assertFalse(card['legal_applicability_verified'])
            self.assertEqual(card['original_url'], source['url'])
            self.assertIn(source['uncompared_alternative_urls'][0], card['uncompared_alternative_urls'])
            store.close()

    def test_insurance_keeps_tail_title_and_all_visible_text(self):
        mod = self.module(); source = self.source(1)
        text, facts = mod.parse_disclosure(self.original(1), source)
        tree = html.fromstring(self.original(1).decode('utf8'))
        body = tree.xpath('//*[@class="contents_div"]')[0]
        for style in body.xpath('./style'):
            style.drop_tree()
        self.assertEqual(''.join(text.split()), ''.join(body.text_content().split()))
        self.assertTrue(text.rstrip().endswith('吉林省安全生产责任保险实施细则'))
        self.assertIn('第四十九条', text)
        self.assertNotIn('FONT-SIZE', text)
        self.assertEqual(facts['publisher'], '吉林省应急管理厅')
        self.assertEqual(len(source['body_issuers']), 7)
        self.assertFalse(facts['source_dates']['created_signature_discrepancy'])

    def test_identity_metadata_mismatches_and_duplicates_rejected(self):
        mod = self.module(); source = self.source()
        for label in ('标题', '发文机关', '发文字号', '成文日期', '发布日期'):
            def mutate(tree):
                for row in tree.xpath('//tr[td[@class="zly_xxgk_style10802"]]'):
                    if ''.join(row[0].text_content().split()).rstrip('：') == label:
                        row[1].text = '错误'
            with self.subTest(label=label), self.assertRaises(ValueError):
                mod.parse_disclosure(self.changed(mutate), source)
        def duplicate(tree):
            row = tree.xpath('//tr[td[@class="zly_xxgk_style10802"]]')[0]
            row.addnext(copy.deepcopy(row))
        with self.assertRaises(ValueError):
            mod.parse_disclosure(self.changed(duplicate), source)

    def test_body_identity_and_signature_mismatch_rejected(self):
        mod = self.module(); source = self.source()
        for before, after in [('吉林省人民政府办公厅关于印发</b>', '错误机关关于印发</b>'),
                              ('2026年8月25日', '2026年8月26日'),
                              ('吉林省人民政府办公厅&nbsp;', '吉林省民政厅&nbsp;')]:
            raw = self.original().decode('utf8')
            self.assertIn(before, raw)
            with self.subTest(before=before), self.assertRaises(ValueError):
                mod.parse_disclosure(raw.replace(before, after).encode(), source)

    def test_unsupported_layout_hidden_and_unknown_css_rejected(self):
        mod = self.module()
        for fragment in ('<table><tr><td>不能丢</td></tr></table>', '<img src="x"/>',
                         '<p hidden="hidden">隐藏</p>', '<p style="display:none">隐藏</p>',
                         '<p style="opacity:0">隐藏</p>', '<p class="unknown">未知</p>',
                         '<script>正文</script>', '<style>p{display:none}</style>',
                         '<a href="a.pdf">附件</a>', '<p aria-hidden="true">隐藏</p>'):
            def append(tree):
                tree.xpath('//*[@class="contents_div"]')[0].append(html.fromstring(fragment))
            for index in (0, 2):
                with self.subTest(index=index, fragment=fragment), self.assertRaises(ValueError):
                    mod.parse_disclosure(self.changed(append, index), self.source(index))
        with self.assertRaises(ValueError):
            mod.parse_disclosure(self.original(1).replace(b'FONT-SIZE: 12pt', b'FONT-SIZE: 0pt'), self.source(1))

    def test_wrapper_tail_text_is_preserved_and_hidden_ancestor_rejected(self):
        mod = self.module()
        def extra(tree):
            body = tree.xpath('//*[@class="contents_div"]')[0]
            body[-1].tail = '额外正文尾注'
        text, _ = mod.parse_disclosure(self.changed(extra), self.source())
        self.assertTrue(text.endswith('额外正文尾注'))
        def hide(tree):
            tree.xpath('//*[@class="contents_div"]')[0].getparent().set('hidden', 'hidden')
        with self.assertRaises(ValueError):
            mod.parse_disclosure(self.changed(hide), self.source())

    def test_storage_atomic_and_raw_original_retained_on_failure(self):
        mod = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); store = LegalStore(root/'test.sqlite3')
            store.db.executescript("CREATE TRIGGER fail_source BEFORE INSERT ON provenance BEGIN SELECT RAISE(ABORT,'source failure'); END;")
            row = mod.ingest_disclosure(root, self.source(), self.reader(self.original()), store)
            self.assertEqual(row['status'], 'failed')
            for table in ('versions', 'search_index', 'provenance', 'audit'):
                self.assertEqual(store.db.execute('SELECT count(*) FROM '+table).fetchone()[0], 0)
            self.assertEqual((root/row['original_path']).read_bytes(), self.original())
            store.close()

    def test_replay_is_idempotent_and_distinct_from_old_sample(self):
        mod = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); store = LegalStore(root/'test.sqlite3')
            rows = [mod.ingest_disclosure(root, self.source(), self.reader(self.original()), store) for _ in range(2)]
            self.assertEqual(rows[0]['version_id'], rows[1]['version_id'])
            self.assertEqual(store.health()['versions'], 1)
            self.assertEqual(store.db.execute('SELECT count(*) FROM audit').fetchone()[0], 2)
            detail = store.detail(rows[0]['version_id'])
            self.assertEqual(detail['law_id'], 'jilin-disclosure:9703553')
            self.assertIn('未比对', detail['locator'])
            self.assertTrue(store.search('消防'))
            store.close()

    def test_exact_url_allowlist_and_config_validation(self):
        mod = self.module()
        for index in (0, 1, 2):
            allowed_url(self.source(index)['url'])
        for url in ('https://xxgk.jl.gov.cn/szf/gkml/other.html', self.source()['url']+'?x=1',
                    'https://xxgk.jl.gov.cn/szf/gkml/202608/t20260825_9687314.html'):
            with self.assertRaises(ValueError):
                allowed_url(url)
        for patch in ({'id': '../bad'}, {'region': 'CN-BJ'}, {'url': 'https://example.com'}, {'status':'pending'}):
            with self.assertRaises(ValueError):
                mod.validate_sources([{**self.source(), **patch}])
        with self.assertRaises(ValueError):
            mod.validate_sources([self.source()]*21)

    def test_straw_exact_url_is_allowed_without_broadening_paths(self):
        url = 'https://xxgk.jl.gov.cn/szf/gkml/202608/t20260825_9687313.html'
        try:
            actual = allowed_url(url)
        except ValueError as error:
            self.fail('已核验的秸秆官方HTML尚未加入精确路径清单：'+str(error))
        self.assertEqual(actual, url)
        for changed in (url+'?x=1', url+'#body', url.replace('9687313', '9687314'),
                        url.replace('20260825', '20260826')):
            with self.subTest(url=changed), self.assertRaises(ValueError):
                allowed_url(changed)

    def test_comparison_notice_must_be_nonempty_text_when_present(self):
        mod = self.module()
        mod.validate_sources([self.source()])
        mod.validate_sources([{**self.source(), 'comparison_notice': '已作局部比较，未认定同版'}])
        for value in (None, '', ' \t\n', 1, [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                mod.validate_sources([{**self.source(), 'comparison_notice': value}])

    def test_existing_locators_and_version_ids_remain_exact(self):
        versions = ('c66d5c3784148604f44314b65931278745bd4affe5edd64d9dccae98b210fd9d',
                    '7f3fdb128770bcf3666860088a672455b9643d6941939433c8f0c58dec31d993')
        locators = (
            '独立官方HTML .contents_div全文；与旧清单及其附件未比对；发布机关为页面元数据字段；正文署名：吉林省人民政府办公厅；页面成文日期2026-08-28与正文落款2026-08-25不一致，均为来源观察值，未确定法律适用日期。原件SHA256=2411277231b5f83ade95998ed3001841b18d891b2d279935c4400d238c6f3234；未经法律审核',
            '独立官方HTML .contents_div全文；与旧清单及其附件未比对；发布机关为页面元数据字段；正文署名：吉林省应急管理厅、吉林省财政厅、吉林省工业和信息化厅、吉林省住房和城乡建设厅、吉林省交通运输厅、吉林省水利厅、国家金融监督管理总局吉林监管局；发布机关字段为吉林省应急管理厅；正文落款为七部门。HTML末尾另有实施细则题名，按原顺序保留；旧清单题名截断，不据此补齐或认定附件同版。原件SHA256=4da992b7c79e0febfa634c5bd5828f4b9bdad6245ad9fae485016338c19871db；未经法律审核')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); store = LegalStore(root/'test.sqlite3')
            for index in (0, 1):
                self.assertNotIn('comparison_notice', self.source(index))
                row = self.module().ingest_disclosure(root, self.source(index), self.reader(self.original(index)), store)
                self.assertEqual(row['version_id'], versions[index])
                self.assertEqual(store.detail(row['version_id'])['locator'], locators[index])
            store.close()

    def test_straw_fulltext_keeps_twenty_items_and_both_complete_county_lists(self):
        text, facts = self.module().parse_disclosure(self.original(2), self.source(2))
        self.assertEqual(len(text), 3880)
        self.assertEqual(hashlib.sha256(text.encode()).hexdigest(),
                         'e6bf07d85a5771b6b148c544a5bdb4d3e540377751918622173f6386d9e5b7de')
        self.assertEqual(re.findall(r'^（([一二三四五六七八九十]+)）', text, re.M),
                         ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十',
                          '十一', '十二', '十三', '十四', '十五', '十六', '十七', '十八', '十九', '二十'])
        for heading in ('一、明确禁止露天焚烧秸秆区域', '二、推进科学还田', '三、做好离田利用',
                        '四、加大金融和科技支持力度', '五、严格焚烧管控', '六、强化组织实施'):
            self.assertIn(heading, text)
        first, second = text.split('一、典型黑土区县（市、区）名单（22个）')[1].split('二、秸秆资源量较大县名单（32个）')
        expected = (
            '双阳区、九台区、公主岭市、榆树市、农安县、德惠市、永吉县、舒兰市、磐石市、蛟河市、桦甸市、梨树县、伊通县、双辽市、东丰县、辉南县、柳河县、宁江区、扶余市、长岭县、前郭县、梅河口市',
            '双阳区、九台区、公主岭市、榆树市、农安县、德惠市、昌邑区、永吉县、舒兰市、磐石市、蛟河市、桦甸市、伊通县、梨树县、双辽市、东丰县、东辽县、辉南县、柳河县、宁江区、前郭县、扶余市、长岭县、乾安县、洮北区、大安市、洮南市、镇赉县、通榆县、敦化市、汪清县、梅河口市')
        for section, names in zip((first, second), expected):
            actual = [name for line in section.splitlines() if line.strip()
                      for name in line.split('：')[-1].split('、')]
            self.assertEqual(actual, names.split('、'))
        self.assertIn('按照不超过0.8%的优惠担保费率', text)
        self.assertNotIn('08%', text)
        self.assertEqual(facts['source_dates']['metadata_created'], '2026-08-15')
        self.assertEqual(facts['source_dates']['metadata_published'], '2026-08-25')
        self.assertEqual(facts['source_dates']['body_signature'], '2026-08-15')

    def test_straw_is_independent_idempotent_and_cites_limited_comparison(self):
        source = self.source(2); mod = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); store = LegalStore(root/'test.sqlite3')
            rows = [mod.ingest_disclosure(root, source, self.reader(self.original(2)), store) for _ in range(2)]
            self.assertEqual(rows[0]['version_id'], rows[1]['version_id'])
            self.assertEqual(store.health()['versions'], 1)
            detail = store.detail(rows[0]['version_id'])
            self.assertEqual(detail['law_id'], 'jilin-disclosure:9687313')
            self.assertNotEqual(detail['law_id'], 'jilin-sample:'+source['sample_id'])
            self.assertTrue(store.search('秸秆'))
            card = citation_for(detail, 0, 20)
            self.assertIn(source['comparison_notice'], card['locator'])
            self.assertNotIn('与旧清单及其附件未比对', card['locator'])
            for literal in ('0.8%', '08%', '第5页', '10页', '4页', '不能认定全文同版',
                            '未通过严格整份PDF验收',
                            'https://www.jlrd.gov.cn/jlsjk/202608/P020260827530388203078.pdf',
                            '05504e97e8e7f12c08dc3112a289095cd385256f656ff07e4064c877de5e55dd',
                            'https://www.jlrd.gov.cn/jlsjk/202608/P020260827530388387152.pdf',
                            '09deb13cb570a9e6724ee0ff76633d7feb78eefd6c67a45b8a70c56bfe1cbd8a'):
                self.assertIn(literal, card['locator'])
            self.assertEqual(card['uncompared_alternative_urls'],
                             ['https://www.jlrd.gov.cn/jlsjk/202608/P020260827530388004847.wps'])
            self.assertEqual(card['compared_pdf_originals'], [])
            self.assertEqual(card['review_state'], 'quarantine')
            self.assertIsNone(card['effective_from'])
            self.assertIsNone(card['effective_to'])
            self.assertFalse(card['legal_applicability_verified'])
            self.assertFalse(card['source_dates_verified'])
            store.close()

    def test_body_attachment_outside_contents_is_not_silently_omitted(self):
        mod = self.module()
        for fragment in ('<a href="original.pdf">附表</a>', '<span>附表正文</span>', '<img src="table.png">'):
            def attachment(tree):
                tree.xpath('//*[@class="wjfj-1026"]')[0].append(html.fromstring(fragment))
            with self.subTest(fragment=fragment), self.assertRaises(ValueError):
                mod.parse_disclosure(self.changed(attachment), self.source())
        def tail(tree):
            tree.xpath('//*[@class="contents_div"]')[0].tail = '遗漏的尾注'
        with self.assertRaises(ValueError):
            mod.parse_disclosure(self.changed(tail), self.source())
        def sibling(tree):
            tree.xpath('//*[@class="contents_div"]')[0].addnext(html.fromstring('<div>新正文</div>'))
        with self.assertRaises(ValueError):
            mod.parse_disclosure(self.changed(sibling), self.source())

    def test_metadata_hidden_values_are_not_used_as_identity(self):
        mod = self.module()
        for xpath in ('//td[@class="zly_xxgk_style20802"]', '//tr[td[@class="zly_xxgk_style10802"]]',
                      '//table[@class="zly_xxgk_20170802"]'):
            def hide(tree):
                tree.xpath(xpath)[0].set('hidden', 'hidden')
            with self.subTest(xpath=xpath), self.assertRaises(ValueError):
                mod.parse_disclosure(self.changed(hide), self.source())

    def test_appendix_script_string_whitespace_is_not_normalized_away(self):
        mod = self.module()
        def change_script(tree):
            script = tree.xpath('//*[@class="wjfj-1026"]/script')[0]
            script.text = script.text.replace("var file_appendix='';", "var file_appendix=' ';")
        with self.assertRaises(ValueError):
            mod.parse_disclosure(self.changed(change_script), self.source())

    def test_article_outer_siblings_are_not_silently_omitted(self):
        mod = self.module()
        for index in (0, 1, 2):
            for fragment in ('<p>外层附文不得遗漏</p>', '<img src="table.png">',
                             '<a href="appendix.pdf">另附表</a>'):
                def append(tree):
                    tree.xpath('//*[@class="contents_div"]')[0].getparent().addnext(html.fromstring(fragment))
                with self.subTest(index=index, fragment=fragment), self.assertRaises(ValueError):
                    mod.parse_disclosure(self.changed(append, index), self.source(index))

    def test_collapsed_metadata_and_new_head_css_are_rejected(self):
        mod = self.module()
        for index in (0, 1, 2):
            def collapse(tree):
                tree.xpath('//tr[td[@class="zly_xxgk_style10802"]]')[0].set('style', 'visibility:collapse')
            def hide_with_css(tree):
                tree.xpath('//head')[0].append(html.fromstring('<style>.contents_div{display:none}</style>'))
            for mutate in (collapse, hide_with_css):
                with self.subTest(index=index, mutation=mutate.__name__), self.assertRaises(ValueError):
                    mod.parse_disclosure(self.changed(mutate, index), self.source(index))

    def test_batch_separate_report_replay_and_shared_lock(self):
        mod = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'verification').mkdir()
            old = root/'verification/jilin-samples-latest.json'
            old.write_text('old report')
            for _ in range(2):
                report = mod.run_disclosures(root, [self.source()], self.reader(self.original()))
                self.assertTrue(report['complete'])
                self.assertEqual(report['human_approved_this_run'], 0)
                self.assertEqual(report['ingested'], 1)
                self.assertIn('比较范围以逐份来源/引用卡说明为准；未法律审核', report['scope'])
            self.assertEqual(old.read_text(), 'old report')
            self.assertTrue((root/'verification/jilin-disclosures-latest.json').is_file())
            with (root/'verification/jilin-samples.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.assertEqual(mod.run_disclosures(root, [self.source()], None)['status'], 'locked')

    def test_bad_body_retains_original_but_does_not_enter_database(self):
        mod = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); store = LegalStore(root/'test.sqlite3')
            row = mod.ingest_disclosure(root, self.source(), self.reader(b'<html>incomplete</html>'), store)
            self.assertEqual(row['status'], 'failed')
            self.assertTrue(row['original_acquired'])
            self.assertEqual(store.health()['versions'], 0)
            store.close()


if __name__ == '__main__':
    unittest.main()
