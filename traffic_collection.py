"""Fixed traffic notice collection: preserve originals, gate each body, then read back.

The manifest is an observed source inventory, not an approval of legal effect.
Unknown bytes or workbook structures never enter the searchable text layer.
"""
import portable_lock as fcntl
import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

from lxml import html

from jilin_disclosures import observed_date, reject_hidden_ancestors
from jilin_sources import allowed_url, compact
from legacy_doc import convert_legacy_doc
from official_docx import extract_docx
from official_monitor import atomic_write, encode, stamp
from scripts.ingest_basic_laws import keep_original
from traffic_workbooks import read_workbook, project_workbook

BASE = Path('data/jilin-samples/traffic')
RECORD_IDS = {'notice', 'rule', *(f'2-{i}' for i in range(1, 9)), '2-7-government', '2-8-government'}
ARCHIVE_IDS = {'renda-parent', 'notice-docx', 'notice-pdf'}


def sha256(body):
    return hashlib.sha256(body).hexdigest()


def validate_manifest(manifest):
    records, archives = manifest['records'], manifest['archives']
    if (manifest['schema_version'] != 1 or manifest['collection_id'] != 'jilin-traffic-2026-2'
            or manifest['region'] != 'CN-JL' or len(records) != 12 or len(archives) != 3
            or {r['id'] for r in records} != RECORD_IDS or {r['id'] for r in archives} != ARCHIVE_IDS):
        raise ValueError('集合清单必须包含通知、规则、八表、两差异版本和三个额外原件')
    parents = {allowed_url(manifest['parent_url']), allowed_url(manifest['renda_parent_url'])}
    seen = set()
    for record in records + archives:
        if not re.fullmatch('[0-9a-f]{64}', record['sha256']) or not record['sources']:
            raise ValueError('原件sha256或来源清单缺失')
        for source in record['sources']:
            url = allowed_url(source['url'])
            if (url in seen or source['parent_url'] not in parents
                    or Path(urlsplit(url).path).suffix != '.' + record['format']
                    or not source['link_label'].strip()):
                raise ValueError('来源重复、格式或父页面关系不符合')
            seen.add(url)
            datetime.fromisoformat(source['acquired_at'])
        if record in records:
            expected = record['id'].removesuffix('-government')
            if record['attachment_id'] != expected or not record['title'].strip():
                raise ValueError('集合附件身份或标题不符合')
    attachments = manifest['attachments']
    if (len(attachments) != 9
            or [a['number'] for a in attachments] != ['1', *(f'2-{i}' for i in range(1, 9))]):
        raise ValueError('父通知的九份附件清单不完整')
    for attachment in attachments:
        matches = [(r, s) for r in records for s in r['sources'] if s['url'] == attachment['url']]
        if len(matches) != 1:
            raise ValueError('父通知附件缺少唯一来源记录')
        record, source = matches[0]
        if (record['attachment_id'] != attachment['attachment_id']
                or source['parent_number'] != attachment['number']
                or source['link_label'] != attachment['label']
                or source['parent_url'] != manifest['parent_url']):
            raise ValueError('网页标号、名称和附件身份不一致')


def parse_notice(payload, manifest):
    """Only the pinned full-page bytes and completely covered body are accepted."""
    record = next(r for r in manifest['records'] if r['id'] == 'notice')
    if sha256(payload) != record['sha256']:
        raise ValueError('通知整页sha256变化，须重新核验')
    tree = html.fromstring(payload.decode('utf-8-sig'))
    titles, bodies = tree.xpath('//title'), tree.xpath('//*[@class="contents_div"]')
    if len(titles) != 1 or compact(titles[0].text_content()) != compact(manifest['title']) or len(bodies) != 1:
        raise ValueError('通知标题或正文区不符合')
    metadata = {}
    for row in tree.xpath('//tr[td[@class="zly_xxgk_style10802"]]'):
        reject_hidden_ancestors(row)
        cells = row.xpath('./td')
        if len(cells) != 2 or any(len(c) for c in cells):
            raise ValueError('通知元数据结构不符合')
        key = compact(cells[0].text_content()).rstrip('：')
        if key in metadata:
            raise ValueError('通知元数据重复')
        metadata[key] = cells[1].text_content()
    for label, key in [('标题', 'title'), ('发文机关', 'publisher'), ('发文字号', 'document_number')]:
        if compact(metadata.get(label, '')) != compact(manifest[key]):
            raise ValueError('通知身份字段不匹配')
    for label, key in [('成文日期', 'metadata_created'), ('发布日期', 'metadata_published')]:
        if observed_date(metadata.get(label, '')) != manifest['source_dates'][key]:
            raise ValueError('通知来源日期变化')
    body = bodies[0]
    for element in body.iter():
        reject_hidden_ancestors(element)
        if element.tag not in {'div', 'p', 'font', 'span', 'b', 'strong', 'br', 'a'}:
            raise ValueError('通知正文包含未核验结构')
    blocks = body.xpath('.//*[self::div or self::p][not(.//div or .//p)]')
    text = '\n\n'.join(p.text_content().strip() for p in blocks if p.text_content().strip())
    if (compact(text) != compact(body.text_content()) or sha256(text.encode()) != manifest['notice_body_sha256']
            or not compact(text).startswith(compact(manifest['title'] + manifest['document_number']))):
        raise ValueError('通知全文未完整覆盖或已核验正文变化')
    actual = [(urljoin(manifest['parent_url'], a.get('href')), a.text_content().strip())
              for a in tree.xpath('//*[@class="wjfj-1026"]//a[@href]')]
    expected = [(a['url'], a['label']) for a in manifest['attachments']]
    if actual != expected:
        raise ValueError('通知附件链接或名称清单不完整')
    for attachment in manifest['attachments']:
        if compact(attachment['label'].rsplit('.', 1)[0]) not in compact(text):
            raise ValueError('通知正文附件声明缺失')
    signature_date = date.fromisoformat(manifest['source_dates']['body_signature'])
    signature = manifest['publisher'] + f'{signature_date.year}年{signature_date.month}月{signature_date.day}日'
    if compact(signature) not in compact(text):
        raise ValueError('父通知署名日期不匹配')
    return text


def check_renda_parent(payload, manifest):
    tree = html.fromstring(payload.decode('utf-8-sig'))
    actual = {}
    for anchor in tree.xpath('//a[@href]'):
        url = urljoin(manifest['renda_parent_url'], anchor.get('href'))
        if Path(urlsplit(url).path).suffix.lower() in ('.doc', '.docx', '.pdf', '.xls', '.xlsx', '.zip', '.rar', '.wps'):
            actual.setdefault(url, set()).add(compact(anchor.text_content()))
    expected = {s['url']: compact(s['link_label'])
                for r in manifest['records'] + manifest['archives'] for s in r['sources']
                if s['parent_url'] == manifest['renda_parent_url'] and s['url'] != manifest['renda_parent_url']}
    if set(actual) != set(expected) or any(label not in actual[url] for url, label in expected.items()):
        raise ValueError('人大父页面附件关系变化或清单遗漏')


def capture(root, record, reader):
    row = {'id': record['id'], 'original_acquired': False, 'parsed': False, 'version_id': None,
           'failure_reason': None, 'sources': [], 'differences': record.get('differences', [])}
    payload = None
    for source in record['sources']:
        result = {'url': source['url'], 'original_acquired': False, 'sha256_matched': False}
        try:
            response = reader.get(source['url'])
            if getattr(response, 'status', 200) != 200:
                raise ValueError('来源未返回200')
            original = response.body
            if not isinstance(original, bytes) or not 0 < len(original) <= 10_000_000:
                raise ValueError('原件须为不超过10MB的非空字节')
            digest = sha256(original)
            folder = root / BASE / digest
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / ('original.' + record['format'])
            keep_original(path, original)
            result.update(original_acquired=True, sha256=digest, original_path=str(path.relative_to(root)))
            if digest != record['sha256']:
                raise ValueError('原件sha256变化，拒绝自动更新固定清单')
            receipt = {**source, 'original_sha256': digest}
            keep_original(folder / ('source-' + sha256(source['url'].encode()) + '.json'), encode(receipt))
            result['sha256_matched'] = True
            payload = original
        except Exception as error:
            result['failure_reason'] = f'{type(error).__name__}: {error}'
        row['sources'].append(result)
    row['original_acquired'] = all(s['original_acquired'] for s in row['sources'])
    if not all(s['sha256_matched'] for s in row['sources']):
        row['failure_reason'] = '; '.join(s.get('failure_reason', '') for s in row['sources'] if not s['sha256_matched'])
        return row, None
    row['original_path'] = row['sources'][0]['original_path']
    return row, payload


def parse_record(root, record, row, payload, notice_text):
    folder = root / BASE / record['sha256']
    details = {'locations': [], 'internal_number': record.get('internal_number'),
               'internal_title': record.get('internal_title'), 'parser': 'traffic-collection-v1'}
    if record['format'] == 'html':
        return notice_text, details
    if record['format'] == 'doc':
        converted, direct = convert_legacy_doc(payload)
        text, check = extract_docx(converted, record['title'])
        if not compact(text) or compact(text) != compact(direct):
            raise ValueError('规则DOC双转换正文不一致或为空')
        # LibreOffice may change ZIP timestamps on replay. Retain the first
        # derivative and independently recheck its body instead of overwriting.
        target = folder / 'converted.docx'
        if target.exists():
            previous, _ = extract_docx(target.read_bytes(), record['title'])
            if previous != text:
                raise ValueError('已保存转换件正文与本次不同')
        else:
            keep_original(target, converted)
        details.update(parser='legacy-doc-double-conversion+strict-docx-v1', extraction_check=check)
        return text, details
    snapshot = read_workbook(payload, '.' + record['format'])
    structure = folder / 'workbook.json'
    encoded = encode(snapshot)
    if structure.exists() and structure.read_bytes() != encoded:
        previous = json.loads(structure.read_bytes())
        if (not previous.get('unsupported') or previous.get('sha256') != record['sha256']):
            raise ValueError('已有成功结构或原件身份不同，拒绝变更归档')
        candidate = folder / ('workbook-' + sha256(encoded) + '.json')
        if candidate.exists():
            if candidate.read_bytes() != encoded:
                raise ValueError('结构摘要文件内容不匹配，拒绝覆盖')
        elif any((folder / name).exists() for name in ('body.txt', 'locations.json', 'provenance.json')):
            raise ValueError('已有正文、定位或来源，拒绝升级结构')
        structure = candidate
    keep_original(structure, encoded)
    row['structure_path'] = str(structure.relative_to(root))
    if snapshot['unsupported']:
        raise ValueError('工作簿结构未核验：' + json.dumps(snapshot['unsupported'], ensure_ascii=False))
    cells = snapshot['sheets'][0]['cells']
    number, title = cells.get('A1', {}).get('raw_text'), cells.get('A2', {}).get('raw_text')
    if number != record['internal_number'] or title != record['internal_title']:
        raise ValueError('文件内标号或标题变化，不能按网页名称覆盖')
    text, locations = project_workbook(snapshot)
    keep_original(folder / 'locations.json', encode(locations))
    details.update(locations=locations, internal_number=number, internal_title=title,
                   parser='traffic-workbooks-v1', reader_versions=snapshot['reader'],
                   structure_path=str(structure.relative_to(root)),
                   locations_path=str((folder / 'locations.json').relative_to(root)))
    return text, details


def ingest_collection(root, manifest, reader, store):
    """Archive all expected sources before parsing; incomplete batches stay explicit."""
    root = Path(root)
    report = {'collection_id': manifest.get('collection_id'), 'complete': False, 'ok': False,
              'at': stamp(), 'attempt_finished': False, 'planned': 12, 'ingested': 0,
              'results': [], 'archives': [], 'legal_review_performed': False}
    locks = root / 'verification'
    locks.mkdir(parents=True, exist_ok=True)
    with (locks / 'jilin-samples.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {**report, 'status': 'locked'}
        reports = root / BASE / 'reports'
        reports.mkdir(parents=True, exist_ok=True)
        path = reports / (uuid4().hex + '.json')
        def save():
            atomic_write(path, encode(report))
            atomic_write(reports / 'latest.json', encode(report))
        save()
        try:
            validate_manifest(manifest)
            keep_original(root / BASE / ('manifest-' + sha256(encode(manifest)) + '.json'), encode(manifest))
            captured = {}
            for kind in ('records', 'archives'):
                for record in manifest[kind]:
                    row, payload = capture(root, record, reader)
                    report['results' if kind == 'records' else 'archives'].append(row)
                    captured[record['id']] = (row, payload)
                    save()
            # Both frozen parent pages must agree with every source relationship.
            notice_row, notice_payload = captured['notice']
            parent_row, parent_payload = captured['renda-parent']
            if notice_payload is None or parent_payload is None:
                raise ValueError('父通知原件未完整通过，附件关系不能核验')
            notice_text = parse_notice(notice_payload, manifest)
            check_renda_parent(parent_payload, manifest)
            for record in manifest['records']:
                row, payload = captured[record['id']]
                if payload is None:
                    continue
                try:
                    text, details = parse_record(root, record, row, payload, notice_text)
                    row['parsed'] = True
                    folder = root / BASE / record['sha256']
                    keep_original(folder / 'body.txt', text.encode())
                    facts = {**details, 'collection_id': manifest['collection_id'], 'attachment_id': record['attachment_id'],
                             'parent_notice': {'title': manifest['title'], 'document_number': manifest['document_number'],
                                               'url': manifest['parent_url'], 'renda_url': manifest['renda_parent_url']},
                             'publisher': manifest['publisher'], 'document_number': manifest['document_number'],
                             'original_url': record['sources'][0]['url'], 'original_sha256': record['sha256'],
                             'original_path': row['original_path'], 'source_format': record['format'],
                             'source_dates': manifest['source_dates'], 'legal_review_performed': False,
                             'source_dates_scope': '父通知的元数据和正文署名观察日期；不是附件创建日期、独立发布日期或法律适用日期',
                             'source_dates_url': manifest['parent_url'],
                             'verified_sources': [{**s, 'original_sha256': record['sha256']} for s in record['sources']],
                             'differences': record.get('differences', []), 'pages': [],
                             'comparison_notice': manifest['notice_comparison'],
                             'check_scope': '固定原件SHA、来源关系、全文/工作簿支持结构和入库回读；非法律效力审核'}
                    keep_original(folder / 'provenance.json', encode(facts))
                    version = store.add(law_id=manifest['collection_id'] + ':' + record['attachment_id'],
                                        title=record['title'], text=text, source_url=record['sources'][0]['url'],
                                        region=manifest['region'], provenance=facts,
                                        locator='交通集合原件SHA256=' + record['sha256'] + '；未经人工法律审核')
                    detail = store.detail(version)
                    if detail is None or detail['text'] != text or detail['provenance'] != facts:
                        raise ValueError('入库正文或来源字段回读不一致')
                    row.update(version_id=version, text_sha256=detail['sha256'], characters=len(text))
                    report['ingested'] += 1
                except Exception as error:
                    row['failure_reason'] = f'{type(error).__name__}: {error}'
                save()
            report['complete'] = report['ingested'] == 12 and all(not r['failure_reason'] for r in report['archives'])
            report['ok'] = report['complete']
        except Exception as error:
            report['failure_reason'] = f'{type(error).__name__}: {error}'
            for row in report['results']:
                if not row['version_id'] and not row['failure_reason']:
                    row['failure_reason'] = report['failure_reason']
        report.update(attempt_finished=True, finished_at=stamp())
        save()
    return report


class CachedReader:
    """Replay archived source receipts and originals without a network fallback."""
    def __init__(self, root, manifest):
        validate_manifest(manifest)
        self.root = Path(root)
        self.sources = {s['url']: (r, s) for r in manifest['records'] + manifest['archives'] for s in r['sources']}

    def get(self, url):
        record, source = self.sources[url]
        folder = self.root / BASE / record['sha256']
        receipt = json.loads((folder / ('source-' + sha256(url.encode()) + '.json')).read_text())
        if receipt != {**source, 'original_sha256': record['sha256']}:
            raise ValueError('离线来源留证与清单不一致')
        body = (folder / ('original.' + record['format'])).read_bytes()
        if sha256(body) != record['sha256']:
            raise ValueError('离线原件sha256变化')
        return SimpleNamespace(body=body, status=200)
