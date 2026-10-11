"""Independently attributed official disclosures; no equivalence or legal approval."""
import portable_lock as fcntl
import copy
import hashlib
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit
from lxml import html

from jilin_sources import DISCLOSURE_PATHS, allowed_url, compact
from legal_store import LegalStore
from official_monitor import atomic_write, encode, stamp
from scripts.ingest_basic_laws import keep_original


def validate_sources(sources):
    if not 1 <= len(sources) <= 20 or len({s['id'] for s in sources}) != len(sources):
        raise ValueError('独立公开页清单须为1至20项且ID唯一')
    for source in sources:
        allowed_url(source['url'])
        if (source.get('status') != 'ready' or source.get('region') != 'CN-JL'
                or not re.fullmatch(r'[0-9]{1,12}', source['id'])
                or urlsplit(source['url']).netloc != 'xxgk.jl.gov.cn'
                or urlsplit(source['url']).path not in DISCLOSURE_PATHS
                or not source['url'].endswith('_'+source['id']+'.html')
                or not re.fullmatch(r'[0-9]{1,12}', source['sample_id'])
                or not all(isinstance(source[k], str) and source[k].strip()
                           for k in ('title', 'publisher', 'document_number', 'observation_notice'))
                or not source['body_issuers'] or not all(isinstance(x, str) and x.strip() for x in source['body_issuers'])):
            raise ValueError('公开页身份、地域或运行状态未核验')
        if ('comparison_notice' in source
                and (not isinstance(source['comparison_notice'], str) or not source['comparison_notice'].strip())):
            raise ValueError('来源比较说明须为非空文字')
        for key in ('metadata_created', 'metadata_published', 'body_signature'):
            date.fromisoformat(source[key])
        for url in source['uncompared_alternative_urls']:
            allowed_url(url)


def observed_date(value):
    match = re.fullmatch(r'(\d{4})年(\d{1,2})月(\d{1,2})日', compact(value))
    if not match:
        raise ValueError('来源日期格式未核验')
    return date(*map(int, match.groups())).isoformat()


def reject_hidden_ancestors(element):
    for node in (element, *element.iterancestors()):
        style = compact(node.get('style', '')).lower()
        if ('hidden' in node.attrib or node.get('aria-hidden') == 'true'
                or any(value in style for value in ('display:none', 'visibility:hidden', 'visibility:collapse', 'opacity:0'))):
            raise ValueError('正文或元数据祖先包含隐形布局')


def parse_disclosure(payload, source):
    validate_sources([source])
    if not 0 < len(payload) <= 10_000_000:
        raise ValueError('原件大小不符合')
    tree = html.fromstring(payload.decode('utf-8-sig'))
    if tree.xpath('//*[@class="wjfj-1026"]//a[@href]'):
        raise ValueError('公开页另含附件，不能只取HTML冒充完整资料')
    metadata = {}
    for row in tree.xpath('//tr[td[@class="zly_xxgk_style10802"]]'):
        reject_hidden_ancestors(row)
        cells = row.xpath('./td')
        if len(cells) != 2:
            raise ValueError('元数据行结构不符合')
        for cell in cells:
            if set(cell.attrib) != {'class'} or len(cell):
                raise ValueError('元数据值含未核验结构或属性')
        label = compact(cells[0].text_content()).rstrip('：')
        if label in metadata:
            raise ValueError('元数据重复')
        metadata[label] = cells[1].text_content().strip()
    for label, key in (('标题', 'title'), ('发文机关', 'publisher'), ('发文字号', 'document_number')):
        if compact(metadata.get(label, '')) != compact(source[key]):
            raise ValueError('公开页标题、机关或文号不匹配')
    for label, key in (('成文日期', 'metadata_created'), ('发布日期', 'metadata_published')):
        if observed_date(metadata.get(label, '')) != source[key]:
            raise ValueError('公开页观察日期变化，需重核')
    headings = tree.xpath('//title')
    if len(headings) != 1 or compact(headings[0].text_content()) != compact(source['title']):
        raise ValueError('页面标题不匹配')
    bodies = tree.xpath('//*[@class="contents_div"]')
    if len(bodies) != 1:
        raise ValueError('正文区不唯一')
    body = bodies[0]
    reject_hidden_ancestors(body)
    # Freeze the whole observed page outside the extracted body, including
    # head CSS/scripts, metadata, outer article wrappers, and every tail.
    template = copy.deepcopy(tree)
    candidates = template.xpath('//*[@class="contents_div"]')
    if len(candidates) != 1:
        raise ValueError('页面模板正文结构变化')
    placeholder = candidates[0]
    for child in list(placeholder):
        placeholder.remove(child)
    placeholder.text = None
    template_digest = hashlib.sha256(html.tostring(template, encoding='unicode', with_tail=True).encode()).hexdigest()
    if template_digest != source['page_template_sha256']:
        raise ValueError('整页模板变化，存在未核验样式、结构或剩余内容')
    styles = body.xpath('./style')
    if [hashlib.sha256(s.text_content().encode()).hexdigest() for s in styles] != source['body_style_sha256']:
        raise ValueError('正文样式模板变化')
    for style in styles:
        if dict(style.attrib) != {'type': 'text/css'}:
            raise ValueError('样式模板属性变化')
        style.drop_tree()
    tags = {'div', 'p', 'font', 'span', 'b', 'strong', 'br'}
    attributes = {'class', 'style', 'face', 'align'}
    allowed_styles = {'font-size': {'16px', '24px'}, 'text-align': {'center', 'justify', 'right'}}
    for element in body.iter():
        if not isinstance(element.tag, str):
            raise ValueError('正文包含未处理注释或结构')
        if (element.tag not in tags or set(element.attrib)-attributes
                or element.get('class') not in (None, 'contents_div', 'Custom_UnionStyle')
                or element.get('align') not in (None, 'center', 'right')
                or element.get('face') not in (None, '楷体')):
            raise ValueError('正文含未处理结构、属性或隐形内容')
        for declaration in element.get('style', '').split(';'):
            if not declaration.strip():
                continue
            key, separator, value = declaration.partition(':')
            if not separator or compact(value).lower() not in allowed_styles.get(compact(key).lower(), set()):
                raise ValueError('正文排版未核验，不能静默忽略')
    signatures = body.xpath('.//*[@align="right" or contains(@style,"right")]')
    signature = ''.join(compact(node.text_content()) for node in signatures)
    expected_date = date.fromisoformat(source['body_signature'])
    expected_signature = ''.join(source['body_issuers']) + f'{expected_date.year}年{expected_date.month}月{expected_date.day}日'
    if signature != expected_signature:
        raise ValueError('正文署名或日期不匹配')
    parts = []
    def visit(element):
        block = element.tag in ('div', 'p', 'br')
        if block:
            parts.append('\n\n')
        parts.append(element.text or '')
        for child in element:
            visit(child)
            parts.append(child.tail or '')
        if block:
            parts.append('\n\n')
    visit(body)
    text = '\n\n'.join(line.strip() for line in ''.join(parts).splitlines() if line.strip())
    if len(text) < 20 or compact(text) != compact(body.text_content()):
        raise ValueError('正文提取未完整覆盖')
    if not compact(text).startswith(compact(source['title']+source['document_number'])):
        raise ValueError('正文开头标题或文号不匹配')
    provenance = {'publisher': metadata['发文机关'], 'document_number': metadata['发文字号'],
                  'original_url': source['url'], 'original_sha256': hashlib.sha256(payload).hexdigest(),
                  'source_format': 'html', 'pages': [],
                  'uncompared_alternative_urls': source['uncompared_alternative_urls'],
                  'source_dates': {key: source[key] for key in ('metadata_created', 'metadata_published', 'body_signature')}}
    provenance['source_dates']['created_signature_discrepancy'] = source['metadata_created'] != source['body_signature']
    return text, provenance


def ingest_disclosure(root, source, reader, store):
    root = Path(root)
    row = {'id': source['id'], 'sample_id': source['sample_id'], 'url': source['url'],
           'at': stamp(), 'status': 'failed', 'phase': 'identity', 'original_acquired': False,
           'legal_review_performed': False}
    try:
        validate_sources([source])
        row['phase'] = 'acquire'
        payload = reader.get(source['url']).body
        digest = hashlib.sha256(payload).hexdigest()
        folder = root/'data/jilin-samples/disclosures'/source['id']/digest
        folder.mkdir(parents=True, exist_ok=True)
        keep_original(folder/'original.html', payload)
        row.update(original_acquired=True, original_sha256=digest,
                   original_path=str((folder/'original.html').relative_to(root)))
        row['phase'] = 'extract'
        text, facts = parse_disclosure(payload, source)
        keep_original(folder/'body.txt', text.encode())
        keep_original(folder/'source.json', encode(source))
        keep_original(folder/'provenance.json', encode(facts))
        row['phase'] = 'store_roundtrip'
        locator = ('独立官方HTML .contents_div全文；'
                   +source.get('comparison_notice', '与旧清单及其附件未比对')+'；'
                   '发布机关为页面元数据字段；正文署名：'+'、'.join(source['body_issuers'])+'；'
                   +source['observation_notice']+'原件SHA256='+digest+'；未经法律审核')
        version = store.add(law_id='jilin-disclosure:'+source['id'], title=source['title'], text=text,
                            source_url=source['url'], region=source['region'], locator=locator, provenance=facts)
        detail = store.detail(version)
        row.update(status='ingested_quarantine' if detail['review_state']=='quarantine' else 'reused_published',
                   version_id=version, text_sha256=detail['sha256'], characters=len(text),
                   review_state=detail['review_state'], source_dates=facts['source_dates'],
                   observation_notice=source['observation_notice'])
    except Exception:
        row['error'] = '独立公开页来源、身份、结构或存储校验未通过；未自动换用旧附件或确认法律效力'
    return row


def run_disclosures(root, sources, reader):
    root = Path(root)
    validate_sources(sources)
    verification = root/'verification'
    verification.mkdir(parents=True, exist_ok=True)
    with (verification/'jilin-samples.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'ok': False, 'complete': False, 'status': 'locked'}
        report = {'at': stamp(), 'planned': len(sources), 'results': [], 'ok': False, 'complete': False,
                  'attempt_finished': False, 'originals_acquired': 0, 'ingested': 0, 'failed': 0,
                  'human_approved_this_run': 0,
                  'scope': '独立官方HTML；旧20项失败报告保留；比较范围以逐份来源/引用卡说明为准；未法律审核'}
        path = verification/'jilin-disclosures-latest.json'
        atomic_write(path, encode(report))
        reader.evidence_root = root/'data/jilin-samples/disclosures/responses'
        store = LegalStore(root/'data/legal.sqlite3')
        try:
            for source in sources:
                row = ingest_disclosure(root, source, reader, store)
                report['results'].append(row)
                report['originals_acquired'] += row['original_acquired']
                report['ingested'] += row['status'] in ('ingested_quarantine', 'reused_published')
                report['failed'] += row['status'] == 'failed'
                atomic_write(path, encode(report))
        finally:
            store.close()
        report.update(ok=report['ingested']==len(sources), complete=report['ingested']==len(sources),
                      attempt_finished=True, finished_at=stamp())
        atomic_write(path, encode(report))
        return report
