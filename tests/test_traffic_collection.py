import copy
import portable_lock as fcntl
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from lxml import html, etree
from openpyxl import Workbook

import legal_mcp
from legal_store import LegalStore
from traffic_workbooks import read_workbook

ROOT = Path(__file__).resolve().parents[1]


def digest(body):
    return hashlib.sha256(body).hexdigest()


def book_bytes(number, title, value='投标保证金不与退还'):
    book = Workbook()
    book.active.title = 'Sheet1'
    for row in ([number], [title], ['代码', '违法行为（案由）', '法律根据', '违法程度', '判断基准', '处罚基准'],
                [7.5, '行为', '第一条 ' + value, '一般', '条件', '处罚']):
        book.active.append(row)
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()


class Reader:
    def __init__(self, bodies):
        self.bodies = bodies
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        return SimpleNamespace(body=self.bodies[url], status=200)


class TrafficCollectionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('traffic_collection'), '交通集合入口尚未实现')
        self.api = __import__('traffic_collection')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = LegalStore(self.root / 'data/legal.sqlite3')
        self.addCleanup(self.store.close)
        self.manifest = json.loads((ROOT / 'config/jilin-traffic.json').read_text())
        self.bodies = {}
        for record in self.manifest['records'] + self.manifest['archives']:
            if record['format'] in ('xlsx', 'xls'):
                payload = book_bytes(record['internal_number'], record['internal_title'],
                                     '投标保证金不予退还' if record['id'] == '2-7-government' else '投标保证金不与退还')
            else:
                payload = ('测试原件 ' + record['id']).encode()
            record['sha256'] = digest(payload)
            for source in record['sources']:
                self.bodies[source['url']] = payload
        # XLS decoding and DOC conversion are external format boundaries. Other
        # tests and actual-file integration cover their strict parsers.
        actual_reader = read_workbook
        self.addCleanup(patch.stopall)
        patch('traffic_collection.read_workbook', side_effect=lambda body, suffix: actual_reader(body, '.xlsx')).start()
        self.rule_text = self.manifest['records'][1]['title'] + '\n第一条 测试公开裁量规则正文，未经人工法律审核。'
        patch('traffic_collection.convert_legacy_doc', return_value=(b'converted docx', self.rule_text)).start()
        patch('traffic_collection.extract_docx', return_value=(self.rule_text, {})).start()
        self.make_parents()

    def make_parents(self):
        m = self.manifest
        title = m['title']
        body = [title, m['document_number'], '通知正文。'] + [
            ('附件：' if i == 0 else '') + a['label'].rsplit('.', 1)[0]
            for i, a in enumerate(m['attachments'])]
        body += [m['publisher'], '2026年7月23日', '初审：测试']
        tree = html.Element('html')
        etree.SubElement(tree, 'title').text = title
        table = etree.SubElement(tree, 'table')
        for name, value in [('标题', title), ('发文机关', m['publisher']), ('发文字号', m['document_number']),
                            ('成文日期', '2026年7月23日'), ('发布日期', '2026年7月27日')]:
            tr = etree.SubElement(table, 'tr')
            etree.SubElement(tr, 'td', {'class': 'zly_xxgk_style10802'}).text = name + '：'
            etree.SubElement(tr, 'td', {'class': 'zly_xxgk_style20802'}).text = value
        content = etree.SubElement(tree, 'div', {'class': 'contents_div'})
        for line in body:
            etree.SubElement(content, 'div').text = line
        links = etree.SubElement(tree, 'div', {'class': 'wjfj-1026'})
        for attachment in m['attachments']:
            etree.SubElement(links, 'a', href=attachment['url']).text = attachment['label']
        payload = html.tostring(tree, encoding='utf-8')
        m['notice_body_sha256'] = digest('\n\n'.join(body).encode())
        m['records'][0]['sha256'] = digest(payload)
        self.bodies[m['parent_url']] = payload
        links = html.Element('html')
        for record in m['records'][1:] + m['archives'][1:]:
            for source in record['sources']:
                if source['parent_url'] == m['renda_parent_url']:
                    etree.SubElement(links, 'a', href=source['url']).text = source['link_label']
        payload = html.tostring(links, encoding='utf-8')
        m['archives'][0]['sha256'] = digest(payload)
        self.bodies[m['renda_parent_url']] = payload
        self.reader = Reader(self.bodies)

    def ingest(self):
        return self.api.ingest_collection(self.root, self.manifest, self.reader, self.store)

    def counts(self):
        return [self.store.db.execute('SELECT count(*) FROM ' + t).fetchone()[0]
                for t in ('versions', 'provenance', 'audit')]

    def test_complete_requires_all_twelve_roundtrips_and_three_archives(self):
        report = self.ingest()
        self.assertTrue(report['complete'], report)
        self.assertEqual(report['ingested'], 12)
        self.assertEqual(len(report['archives']), 3)
        for row in report['results']:
            self.assertTrue(row['original_acquired'])
            self.assertTrue(row['parsed'])
            self.assertIsNone(row['failure_reason'])
            self.assertIsNotNone(self.store.detail(row['version_id']))
        self.assertEqual(self.store.health()['published'], 0)

    def test_omitting_each_required_record_cannot_complete_or_write(self):
        original = copy.deepcopy(self.manifest)
        for index in range(12):
            self.manifest = copy.deepcopy(original)
            del self.manifest['records'][index]
            report = self.ingest()
            self.assertFalse(report['complete'])
            self.assertEqual(self.counts(), [0, 0, 0])

    def test_missing_any_original_or_changed_sha_keeps_collection_incomplete(self):
        missing = self.manifest['records'][3]['sources'][1]['url']
        del self.bodies[missing]
        replacement = self.manifest['records'][2]['sources'][0]['url']
        self.bodies[replacement] = b'unreviewed replacement'
        report = self.ingest()
        self.assertFalse(report['complete'])
        rows = {r['id']: r for r in report['results']}
        self.assertFalse(rows['2-1']['parsed'])
        self.assertIn('sha256', rows['2-1']['failure_reason'])
        self.assertIsNone(rows['2-2']['version_id'])
        self.assertGreater(report['ingested'], 0)

    def test_collects_all_originals_before_first_parser(self):
        with patch('traffic_collection.convert_legacy_doc', side_effect=lambda body: (
                self.assertEqual(len(set(self.reader.calls)), len(self.bodies)) or b'converted docx', self.rule_text)):
            self.assertTrue(self.ingest()['complete'])

    def test_same_bytes_keep_all_sources_and_replay_adds_no_audit(self):
        report = self.ingest()
        before = self.counts()
        second = self.ingest()
        self.assertTrue(second['complete'], second)
        self.assertEqual(before, [12, 12, 24])
        self.assertEqual(self.counts(), before)
        row = next(r for r in report['results'] if r['id'] == '2-1')
        facts = self.store.detail(row['version_id'])['provenance']
        self.assertEqual(len(facts['verified_sources']), 2)
        self.assertEqual({s['url'] for s in facts['verified_sources']},
                         {s['url'] for s in self.manifest['records'][2]['sources']})
        self.assertFalse(Path(facts['original_path']).is_absolute())
        self.assertFalse(facts['legal_review_performed'])

    def test_parent_dates_have_explicit_scope_and_never_become_effective_dates(self):
        report = self.ingest()
        detail = self.store.detail(report['results'][2]['version_id'])
        facts = detail['provenance']
        self.assertIn('父通知', facts.get('source_dates_scope', ''))
        self.assertEqual(facts.get('source_dates_url'), self.manifest['parent_url'])
        self.assertIsNone(detail['effective_from'])
        self.assertIsNone(detail['effective_to'])

    def test_signature_date_mismatch_blocks_parent_relationship(self):
        self.manifest['source_dates']['body_signature'] = '2030-01-01'
        report = self.ingest()
        self.assertFalse(report['complete'])
        self.assertEqual(self.counts(), [0, 0, 0])

    def test_failure_can_resume_without_changing_successful_versions(self):
        url = self.manifest['records'][3]['sources'][1]['url']
        saved = self.bodies.pop(url)
        first = self.ingest()
        self.assertFalse(first['complete'])
        self.bodies[url] = saved
        second = self.ingest()
        self.assertTrue(second['complete'])
        successful = {r['id']: r['version_id'] for r in first['results'] if r['version_id']}
        self.assertTrue(all(successful.get(r['id'], r['version_id']) == r['version_id'] for r in second['results']))
        self.assertEqual(self.counts(), [12, 12, 24])

    def test_cross_source_conflicts_keep_versions_parent_number_and_internal_number(self):
        report = self.ingest()
        rows = {r['id']: self.store.detail(r['version_id']) for r in report['results']}
        for attachment in ('2-7', '2-8'):
            a, b = rows[attachment], rows[attachment + '-government']
            self.assertEqual(a['law_id'], b['law_id'])
            self.assertNotEqual(a['version_id'], b['version_id'])
            self.assertTrue(a['provenance']['differences'])
        facts = rows['2-8-government']['provenance']
        self.assertEqual(facts['internal_number'], '附件2-7')
        self.assertEqual(facts['verified_sources'][0]['parent_number'], '2-8')
        self.assertIn('地方铁路管理', facts['internal_title'])
        self.assertIn('2-8.', facts['verified_sources'][0]['link_label'])

    def test_conflict_citation_links_both_originals_even_if_other_body_is_blocked(self):
        new = next(r for r in self.manifest['records'] if r['id'] == '2-7-government')
        self.bodies[new['sources'][0]['url']] = b'unreviewed replacement'
        report = self.ingest()
        self.assertIsNone(next(r for r in report['results'] if r['id'] == '2-7-government')['version_id'])
        from legal_citations import citation_for
        for attachment in ('2-7', '2-8'):
            row = next(r for r in report['results'] if r['id'] == attachment)
            card = citation_for(self.store.detail(row['version_id']), 0, 1000)
            difference = card['differences'][0]
            old = next(r for r in self.manifest['records'] if r['id'] == attachment)
            new = next(r for r in self.manifest['records'] if r['id'] == attachment + '-government')
            self.assertEqual(difference.get('old_url'), old['sources'][0]['url'])
            self.assertEqual(difference.get('new_url'), new['sources'][0]['url'])

    def test_unknown_workbook_structure_is_archived_and_not_searchable(self):
        with patch('traffic_collection.read_workbook', return_value={
                'unsupported': [{'code': 'biff_semantics_unverified'}], 'sheets': []}):
            report = self.ingest()
        self.assertFalse(report['complete'])
        row = next(r for r in report['results'] if r['id'] == '2-1')
        self.assertTrue(row['original_acquired'])
        self.assertFalse(row['parsed'])
        self.assertIn('biff_semantics_unverified', row['failure_reason'])
        self.assertTrue((self.root / row['structure_path']).exists())

    def test_real_supported_workbooks_survive_json_archive_and_store_roundtrip(self):
        for record_id, name in [('2-1', 'transport.xlsx'), ('2-7', 'construction.xlsx')]:
            record = next(r for r in self.manifest['records'] if r['id'] == record_id)
            payload = (ROOT / 'tests/fixtures/traffic' / name).read_bytes()
            record['sha256'] = digest(payload)
            for source in record['sources']:
                self.bodies[source['url']] = payload
        report = self.ingest()
        self.assertTrue(report['complete'], report.get('failure_reason'))
        row = next(r for r in report['results'] if r['id'] == '2-1')
        snapshot = json.loads((self.root / row['structure_path']).read_text())
        self.assertEqual(len(snapshot['sheets']), 2)
        facts = self.store.detail(row['version_id'])['provenance']
        self.assertTrue(any(loc['row'] is None for loc in facts['locations']))

    def test_repaired_blocked_structure_is_saved_separately_and_replay_is_idempotent(self):
        record = next(r for r in self.manifest['records'] if r['id'] == '2-7-government')
        payload = self.bodies[record['sources'][0]['url']]
        supported = read_workbook(payload, '.xlsx')
        blocked = copy.deepcopy(supported)
        blocked['unsupported'] = [{'code': 'xml_structure', 'detail': '旧解析器尚未支持'}]
        folder = self.root / self.api.BASE / record['sha256']
        folder.mkdir(parents=True)
        old = self.api.encode(blocked)
        (folder / 'workbook.json').write_bytes(old)
        report = self.ingest()
        row = next(r for r in report['results'] if r['id'] == record['id'])
        self.assertIsNotNone(row['version_id'], row['failure_reason'])
        expected = folder / ('workbook-' + digest(self.api.encode(supported)) + '.json')
        self.assertEqual(self.root / row['structure_path'], expected)
        self.assertEqual((folder / 'workbook.json').read_bytes(), old)
        facts = self.store.detail(row['version_id'])['provenance']
        self.assertEqual(self.root / facts['structure_path'], expected)
        before = self.store.db.execute('SELECT * FROM audit ORDER BY id').fetchall()
        files = {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}
        replay = self.ingest()
        again = next(r for r in replay['results'] if r['id'] == record['id'])
        self.assertEqual(again['version_id'], row['version_id'], again['failure_reason'])
        self.assertEqual(self.store.db.execute('SELECT * FROM audit ORDER BY id').fetchall(), before)
        self.assertEqual({p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}, files)

    def test_successful_structure_change_cannot_replace_existing_derivatives(self):
        first = self.ingest()
        record = next(r for r in self.manifest['records'] if r['id'] == '2-1')
        folder = self.root / self.api.BASE / record['sha256']
        before = {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}
        snapshot = json.loads((folder / 'workbook.json').read_text())
        snapshot['observations']['unexpected_reader_change'] = True
        row = {}
        with patch('traffic_collection.read_workbook', return_value=snapshot):
            with self.assertRaises(ValueError):
                self.api.parse_record(self.root, record, row, self.bodies[record['sources'][0]['url']], '')
        self.assertEqual({p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}, before)

    def test_blocked_structure_upgrade_refuses_existing_body(self):
        record = next(r for r in self.manifest['records'] if r['id'] == '2-1')
        payload = self.bodies[record['sources'][0]['url']]
        snapshot = read_workbook(payload, '.xlsx')
        blocked = copy.deepcopy(snapshot)
        blocked['unsupported'] = [{'code': 'xml_structure'}]
        folder = self.root / self.api.BASE / record['sha256']
        folder.mkdir(parents=True)
        old = self.api.encode(blocked)
        (folder / 'workbook.json').write_bytes(old)
        (folder / 'body.txt').write_text('已有正文')
        with self.assertRaises(ValueError):
            self.api.parse_record(self.root, record, {}, payload, '')
        self.assertEqual((folder / 'workbook.json').read_bytes(), old)
        self.assertEqual((folder / 'body.txt').read_text(), '已有正文')

    def test_rule_double_conversion_disagreement_blocks_only_rule(self):
        with patch('traffic_collection.convert_legacy_doc', return_value=(b'docx', '另一份正文')):
            report = self.ingest()
        self.assertFalse(report['complete'])
        rule = next(r for r in report['results'] if r['id'] == 'rule')
        self.assertIn('转换', rule['failure_reason'])
        self.assertIsNone(rule['version_id'])

    def test_notice_attachment_removal_even_with_updated_hash_is_rejected(self):
        tree = html.fromstring(self.bodies[self.manifest['parent_url']])
        link = tree.xpath('//*[@class="wjfj-1026"]/a')[0]
        link.getparent().remove(link)
        payload = html.tostring(tree)
        self.bodies[self.manifest['parent_url']] = payload
        self.manifest['records'][0]['sha256'] = digest(payload)
        self.assertFalse(self.ingest()['complete'])
        self.assertEqual(self.counts(), [0, 0, 0])

    def test_parent_failure_explains_every_blocked_body(self):
        del self.bodies[self.manifest['parent_url']]
        report = self.ingest()
        self.assertFalse(report['complete'])
        self.assertTrue(all(row['failure_reason'] for row in report['results']))
        self.assertEqual(self.counts(), [0, 0, 0])

    def test_each_attachment_download_is_required_for_complete(self):
        for record in self.manifest['records'][1:]:
            url = record['sources'][0]['url']
            body = self.bodies.pop(url)
            report = self.ingest()
            self.assertFalse(report['complete'], record['id'])
            blocked = next(row for row in report['results'] if row['id'] == record['id'])
            self.assertIsNone(blocked['version_id'])
            self.assertTrue(blocked['failure_reason'])
            self.bodies[url] = body

    def test_archive_failure_does_not_claim_complete_or_html_docx_equivalence(self):
        del self.bodies[self.manifest['archives'][1]['sources'][0]['url']]
        report = self.ingest()
        self.assertFalse(report['complete'])
        self.assertEqual(report['ingested'], 12)
        notice = self.store.detail(report['results'][0]['version_id'])
        self.assertIn('未确认', notice['provenance']['comparison_notice'])

    def test_cli_offline_failure_is_bounded_and_reports_incomplete(self):
        config = self.root / 'manifest.json'
        config.write_text(json.dumps(self.manifest))
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/ingest_jilin_traffic.py'),
                                 '--root', str(self.root), '--manifest', str(config), '--offline'],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report['complete'])
        self.assertEqual(report['ingested'], 0)

    def test_notice_text_outside_leaf_blocks_or_unchecked_title_is_rejected(self):
        tree = html.fromstring(self.bodies[self.manifest['parent_url']])
        tree.xpath('//*[@class="contents_div"]')[0].text = '不得遗漏的文本'
        payload = html.tostring(tree)
        self.bodies[self.manifest['parent_url']] = payload
        self.manifest['records'][0]['sha256'] = digest(payload)
        self.assertFalse(self.ingest()['complete'])
        self.assertEqual(self.counts(), [0, 0, 0])

    def test_corrupt_existing_original_is_never_overwritten(self):
        self.ingest()
        record = self.manifest['records'][2]
        path = self.root / 'data/jilin-samples/traffic' / record['sha256'] / 'original.xlsx'
        path.write_bytes(b'wrong bytes')
        report = self.ingest()
        self.assertFalse(report['complete'])
        self.assertEqual(path.read_bytes(), b'wrong bytes')

    def test_shared_jilin_lock_blocks_writes(self):
        folder = self.root / 'verification'
        folder.mkdir()
        with (folder / 'jilin-samples.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            report = self.ingest()
        self.assertFalse(report['complete'])
        self.assertEqual(report['status'], 'locked')
        self.assertEqual(self.reader.calls, [])

    def test_offline_reader_uses_portable_archived_originals(self):
        self.assertTrue(self.ingest()['complete'])
        self.reader = self.api.CachedReader(self.root, self.manifest)
        self.assertTrue(self.ingest()['complete'])
        self.assertEqual(self.counts(), [12, 12, 24])


class TrafficIntegrationSurfaceTests(unittest.TestCase):
    def test_fixed_manifest_hashes_identity_and_no_diagnostic_paths(self):
        raw = (ROOT / 'config/jilin-traffic.json').read_text()
        m = json.loads(raw)
        self.assertNotIn('verification/', raw)
        self.assertNotIn('/Users/', raw)
        self.assertEqual(len(m['records']), 12)
        self.assertEqual(len(m['attachments']), 9)
        self.assertEqual(m['records'][1]['sha256'], 'f1e45b22ae017df5f10c215124b764d7b773ea3f39efa6e8bd13fe7405b9c96d')
        self.assertEqual([r['sha256'] for r in m['records'][2:10]], [
            'fb57f44caeb05e11c44fdd151cd3ee965dd0e428af3297760d3121efae30a6df',
            'fb163cf8da6166ebfd841c56f1c62361fd64c0c5bc26f8d54813cb5d6a07eef1',
            '39ddc517855ff28130c1bcda7fcb35886c8e68a0a64281ba6ea863233b304a78',
            '3d472e31d50f707e4a05ab13dfdb487d98a8b374b8bb0b14e934ca415dc21682',
            'c4b761d77df7587b1d7b362c3e9da91dd5e061bd84b64a38f0bbf961777f3209',
            'ccc57a97da3d3be87df42f55dadedc9d0f6bd920ef80147246783faebd54c176',
            '8c1b11d3e3d14568ec5911a6ed29fad376c42dc3b4dccbbe7308e0eb57bf54c4',
            'f71364c1a92d53900005acf22a23682a8aa5a8601bb9cd06b25f1d73d1266d5e'])
        self.assertEqual(m['records'][-1]['sources'][0]['url'].split('/')[-1], 'P020260727327348173424.xlsx')

    def test_only_exact_government_traffic_paths_added_to_reader(self):
        from jilin_sources import allowed_url
        m = json.loads((ROOT / 'config/jilin-traffic.json').read_text())
        for url in [m['parent_url'], *[a['url'] for a in m['attachments']]]:
            try:
                allowed = allowed_url(url)
            except ValueError:
                allowed = None
            self.assertEqual(allowed, url, '固定交通来源尚未放行')
        for url in [m['parent_url'] + '?other=1', m['parent_url'].replace('9670745', '9999999'),
                    m['attachments'][-1]['url'].replace('173424', '173425')]:
            with self.assertRaises(ValueError):
                allowed_url(url)

    def test_manifest_is_in_transfer_allowlist(self):
        from library_transfer import _allowed
        self.assertTrue(_allowed('config/jilin-traffic.json'))

    def test_workbook_article_rejected_and_fragment_has_intersecting_coordinates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'law.sqlite3'
            store = LegalStore(path)
            self.addCleanup(store.close)
            text = '第一条 引用法律的文字。\n下一行内容'
            locations = [{'start': 0, 'end': 13, 'sheet': 'Sheet1', 'row': 4, 'cells': [{'source_coordinate': 'C4'}]},
                         {'start': 13, 'end': len(text), 'sheet': 'Sheet1', 'row': 5, 'cells': []}]
            facts = {'source_format': 'xlsx', 'collection_id': 'traffic', 'locations': locations,
                     'parent_notice': {'url': 'https://example.org/notice'}, 'verified_sources': [{'url': 'https://example.org/table'}],
                     'differences': [{'coordinate': 'C55'}]}
            version = store.add(law_id='traffic', title='裁量表', text=text, source_url='https://example.org/table',
                                region='CN-JL', locator='原件', provenance=facts)
            with patch.object(legal_mcp, 'DB', path):
                article = legal_mcp.get_law_article(version, '第一条')
                self.assertFalse(article['found'])
                self.assertIn('get_law_fragment', article['notice'])
                card = legal_mcp.get_law_fragment(version, 0, 13)['citation']
                self.assertEqual(card['locations'], locations[:1])
                self.assertEqual(card['parent_notice'], facts['parent_notice'])
                self.assertEqual(card['verified_sources'], facts['verified_sources'])
                self.assertEqual(card['differences'], facts['differences'])
                self.assertEqual(legal_mcp.get_law_fragment(version, 999, 1)['citation']['locations'], [])


if __name__ == '__main__':
    unittest.main()
