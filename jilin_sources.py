"""Fixed public Jilin sample capture; no login, broad crawl or automatic approval."""
import hashlib
import portable_lock as fcntl
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from lxml import html
from scrapling.fetchers import Fetcher
from scrapling.engines.toolbelt.custom import Response

from official_monitor import atomic_write, encode, stamp
from official_docx import extract_docx
from official_pdf import extract_pdf
from legacy_doc import convert_legacy_doc
from scripts.ingest_basic_laws import keep_original
from legal_store import LegalStore
from robots_policy import confirmed_robots

AGENT = 'ChihengLegalResearch/0.1'
HOSTS = {'www.jlrd.gov.cn': ('/jlsjk/',), 'xxgk.jl.gov.cn': ('/szf/gzk/', '/PDFfile/'),
         'was.jl.gov.cn': ('/was5/web/gov/renda/response_renda_guizhangku20230807.jsp',
                         '/was5/web/gov/szfgz/response_szf_guizhang.jsp')}
DISCLOSURE_PATHS = {
    '/szf/gkml/202609/t20260908_9703553.html',
    '/zsjg/aqjg/xxgkmlqy/202607/t20260731_9673733.html',
    '/szf/gkml/202608/t20260825_9687313.html',
}
TRAFFIC_PATHS = {'/zcbm/fgw_98037/xxgkmlqy/202607/' + name for name in (
    't20260727_9670745.html', 'P020260727327347182510.doc', 'P020260727327347415415.xlsx',
    'P020260727327347576297.xls', 'P020260727327347677392.xls', 'P020260727327347783233.xls',
    'P020260727327347887488.xls', 'P020260727327347975794.xls',
    'P020260817491867840900.xlsx', 'P020260727327348173424.xlsx')}


def allowed_url(url):
    part = urlsplit(url)
    disclosure = part.netloc == 'xxgk.jl.gov.cn' and part.path in DISCLOSURE_PATHS | TRAFFIC_PATHS and not part.query
    if (part.scheme != 'https' or part.netloc not in HOSTS or part.fragment
            or '..' in part.path or '%' in part.path
            or not (disclosure or part.path == '/robots.txt' or any(part.path.startswith(p) for p in HOSTS[part.netloc]))):
        raise ValueError('不在核验过的官方路径范围')
    return url


def normal_fetch(url):
    payload = bytearray()
    def receive(chunk):
        if len(payload) + len(chunk) > 10_000_000:
            return 0
        payload.extend(chunk)
        return len(chunk)
    result = Fetcher.get(url, impersonate=None, stealthy_headers=False, verify=True,
                         follow_redirects=False, retries=0, timeout=20,
                         headers={'User-Agent': AGENT, 'Accept-Encoding': 'identity'}, content_callback=receive)
    if result.headers.get('content-encoding', 'identity').lower() != 'identity':
        raise ValueError('意外压缩传输')
    return Response(url=url, content=bytes(payload), status=result.status, reason='public read',
                    cookies={}, headers=result.headers, request_headers={})


class PublicReader:
    def __init__(self, fetch=normal_fetch, delay=2, evidence_root=None):
        self.fetch, self.delay, self.robots = fetch, delay, {}
        self.evidence_root = evidence_root

    def receive(self, url):
        response = self.fetch(url)
        if self.evidence_root is not None:
            metadata = {'url':url, 'status':response.status,
                        'sha256':hashlib.sha256(response.body).hexdigest()}
            folder = self.evidence_root / hashlib.sha256(encode(metadata)).hexdigest()
            folder.mkdir(parents=True, exist_ok=True)
            keep_original(folder/'response.bin', response.body)
            keep_original(folder/'metadata.json', encode(metadata))
        return response

    def get(self, url):
        allowed_url(url)
        origin = 'https://' + urlsplit(url).netloc
        if origin not in self.robots:
            response = self.receive(origin + '/robots.txt')
            self.robots[origin] = confirmed_robots(response)
        if not self.robots[origin].can_fetch(AGENT, url):
            raise ValueError('robots禁止读取')
        time.sleep(self.delay)
        response = self.receive(url)
        if response.status != 200:
            raise ValueError('来源未返回200，停止本项')
        return response


def compact(value):
    return ''.join(value.split())


def region_code(name, issuer):
    codes = {'吉林省':'CN-JL','长春市':'CN-JL-CC','松原市':'CN-JL-SY'}
    if name not in codes or not issuer.startswith(name):
        raise ValueError('地域/制定主体未核实，不能默认全省适用')
    return codes[name]


def extract_rule(payload, title):
    tree = html.fromstring(payload.decode('utf-8-sig'))
    heading = tree.xpath('//*[@id="zoom"]//*[@class="DOCTITLE"]')
    body = tree.xpath('//*[@id="zoom"]//*[@class="Custom_UnionStyle"]')
    if not body:
        # Observed older rule template has one direct, left-aligned wrapper.
        zoom = tree.xpath('//*[@id="zoom"]')
        children = [x for x in zoom[0] if isinstance(x.tag,str)] if len(zoom)==1 else []
        children = [x for x in children if not (x.tag=='div' and not len(x)
                    and not compact(x.text_content())
                    and compact(x.get('style','')).lower().rstrip(';')=='display:none')]
        if len(children)==1 and children[0].tag=='div' and compact(children[0].get('style','')).lower()=='text-align:left;':
            if compact(children[0].text_content()) != compact(zoom[0].text_content()):
                raise ValueError('正文包装之外仍有文字，不能遗漏')
            body = children
    issuer = tree.xpath('//*[@class="rul_note"]')
    if len(body) != 1 or len(issuer) != 1 or compact(issuer[0].text_content()) != '吉林省人民政府发布':
        raise ValueError('正文区或发布机关不匹配')
    if body[0].xpath('.//*[@class="DOCTITLE" or @class="DocAbstract"]'):
        raise ValueError('未核验的嵌套标题布局，拒绝重复拼接')
    allowed = {'div','p','font','span','br','b','strong','i','em','u','sup','sub'}
    for element in body[0].iter():
        if not isinstance(element.tag,str):
            continue
        style = compact(element.get('style','')).lower()
        if (element.tag not in allowed or 'hidden' in element.attrib
                or 'display:none' in style or 'visibility:hidden' in style):
            raise ValueError('正文含未处理结构或隐形内容，不能静默省略')
        if element.tag=='br':
            element.tail = '\n' + (element.tail or '')
    blocks = body[0].xpath('.//*[self::p or self::div][not(.//p or .//div)]')
    paragraphs = [p.text_content().strip() for p in blocks if p.text_content().strip()]
    if not paragraphs or compact(''.join(paragraphs)) != compact(body[0].text_content()):
        raise ValueError('正文有未提取部分')
    abstracts = tree.xpath('//*[@id="zoom"]//*[@class="DocAbstract"]')
    if not heading:
        # Observed official template: heading and enactment line are visible
        # body paragraphs; the obsolete DOCTITLE template is commented out.
        if compact(paragraphs[0]) != compact(title) or len(paragraphs)<2 or '吉林省人民政府令' not in compact(paragraphs[1]):
            raise ValueError('正文标题或公布机关不匹配')
        return '\n\n'.join(paragraphs)
    if len(heading)!=1 or compact(heading[0].text_content())!=compact(title):
        raise ValueError('标题不匹配')
    return '\n\n'.join([title] + [x.text_content().strip() for x in abstracts] + paragraphs)


def detail_attachments(payload, url, title, issuer, *, preferred_format=None, compare_duplicate_pdfs=False):
    tree = html.fromstring(payload.decode('utf-8-sig'))
    headings = tree.xpath('//*[@class="bt"]')
    issuers = tree.xpath('//*[@id="zdztText"]')
    if (len(headings) != 1 or compact(headings[0].text_content()) != compact(title)
            or len(issuers) != 1 or compact(issuers[0].text_content()) != compact(issuer)):
        raise ValueError('详情标题或制定主体不一致')
    document_types = ('.docx', '.doc', '.pdf', '.xls', '.xlsx', '.zip', '.rar', '.wps', '.odt', '.rtf')
    links = {}
    for anchor in tree.xpath('//a[@href]'):
        link = anchor.get('href')
        if urlsplit(link).path.lower().endswith(document_types):
            absolute = urljoin(url, link)
            if urlsplit(absolute).netloc != urlsplit(url).netloc:
                raise ValueError('附件跨域')
            allowed_url(absolute)
            links.setdefault(absolute, set()).add(compact(anchor.text_content()))
    if not links:
        raise ValueError('正文附件缺失')
    if len(links)>1:
        suffixes = [Path(urlsplit(link).path).suffix.lower() for link in links]
        duplicates = {suffix for suffix in suffixes if suffixes.count(suffix)>1}
        if duplicates and not (compare_duplicate_pdfs and duplicates=={'.pdf'} and suffixes.count('.pdf')<=3):
            raise ValueError('同格式多个文件，需核对版本或附件关系')
        filename_stems = []
        for link, labels in links.items():
            suffix = Path(urlsplit(link).path).suffix.lower()
            if suffix not in ('.doc','.docx','.wps','.pdf'):
                raise ValueError('不能确认同名格式候选，需单独处理附件')
            filename_stems.append({label[:-len(suffix)] for label in labels
                                   if label.lower().endswith(suffix) and label[:-len(suffix)]})
        # Download names can have sequence numbers, brackets or truncation.
        # Shared names group candidates, NOT proof of equal contents. The
        # selected body's legal title is independently checked during extraction.
        if not set.intersection(*filename_stems):
            raise ValueError('不能确认同名格式候选，需单独处理附件')
    supported = [link for link in links if Path(urlsplit(link).path).suffix.lower() in ('.docx','.doc','.pdf')]
    if not supported:
        raise ValueError('正文附件格式尚不支持')
    if preferred_format is not None:
        if preferred_format not in ('docx','doc','pdf'):
            raise ValueError('指定的原件格式不支持')
        supported = [link for link in supported if Path(urlsplit(link).path).suffix.lower()=='.'+preferred_format]
        if not supported:
            raise ValueError('详情页不存在指定格式，不自动换用其他原件')
    selected = min(supported, key=lambda link: ('.docx','.doc','.pdf').index(Path(urlsplit(link).path).suffix.lower()))
    return selected, sorted(link for link in links if link!=selected)


def detail_attachment(payload, url, title, issuer):
    return detail_attachments(payload,url,title,issuer)[0]


def ingest_sample(root, sample, reader, store):
    row = dict(sample, at=stamp(), status='failed', phase='identity', original_acquired=False)
    try:
        region = region_code(sample['region_name'], sample['issuer'])
        is_rule_site = urlsplit(sample['url']).netloc == 'xxgk.jl.gov.cn'
        if is_rule_site != (sample['kind']=='government_rule'):
            raise ValueError('来源与资料类型不匹配')
        if is_rule_site and (sample['issuer']!='吉林省人民政府' or sample['region_name']!='吉林省'):
            raise ValueError('省政府规章来源不能标作其他制定机关')
        row['phase'] = 'detail'
        detail = reader.get(sample['url']).body
        detail_hash = hashlib.sha256(detail).hexdigest()
        directory = root / 'data/jilin-samples' / sample['id']
        directory.mkdir(parents=True, exist_ok=True)
        keep_original(directory / (detail_hash + '.html'), detail)
        row['detail_sha256'] = detail_hash
        if sample['kind'] == 'government_rule':
            original, extension = detail, '.html'
            text = None
        else:
            row['phase'] = 'attachment'
            url, alternatives = detail_attachments(detail, sample['url'], sample['title'], sample['issuer'],
                                                    preferred_format=sample.get('preferred_format'),
                                                    compare_duplicate_pdfs=True)
            row['uncompared_alternative_urls'] = alternatives
            row['attachment_url'] = url
            original = reader.get(url).body
            extension = Path(urlsplit(url).path).suffix.lower()
            text = None
        digest = hashlib.sha256(original).hexdigest()
        folder = directory / digest
        folder.mkdir(exist_ok=True)
        path = folder / ('original' + extension)
        keep_original(path, original)
        row.update(original_acquired=True, original_sha256=digest, original_path=str(path.relative_to(root)))
        row['phase'] = 'extract'
        pdf_manifest = None
        if extension == '.html':
            text = extract_rule(original, sample['title'])
        elif extension == '.pdf':
            text, pdf_manifest = extract_pdf(original, sample['title'])
            keep_original(folder / 'pdf-extraction.json', encode(pdf_manifest))
        else:
            payload = original
            direct = None
            if extension == '.doc':
                payload, direct = convert_legacy_doc(original)
                keep_original(folder / 'converted.docx', payload) if not (folder / 'converted.docx').exists() else None
            text, check = extract_docx(payload, sample['title'])
            if direct is not None and compact(text) != compact(direct):
                raise ValueError('转换正文和直接文本不一致')
        if len(text.strip()) < 20:
            raise ValueError('正文过短')
        keep_original(folder / 'body.txt', text.encode())
        keep_original(folder / 'source.json', encode(sample))
        if not is_rule_site:
            pdf_urls = sorted(link for link in [url, *alternatives]
                              if Path(urlsplit(link).path).suffix.lower()=='.pdf')
            if len(pdf_urls)>1:
                row['phase'] = 'compare_pdf_copies'
                row['compared_pdf_originals'] = []
                for pdf_url in pdf_urls:
                    other_original = original if pdf_url==url else reader.get(pdf_url).body
                    other_hash = hashlib.sha256(other_original).hexdigest()
                    other_folder = directory / other_hash
                    other_folder.mkdir(exist_ok=True)
                    keep_original(other_folder / 'original.pdf', other_original)
                    other_text, other_manifest = ((text,pdf_manifest) if pdf_url==url
                                                   else extract_pdf(other_original,sample['title']))
                    keep_original(other_folder / 'pdf-extraction.json', encode(other_manifest))
                    keep_original(other_folder / 'body.txt', other_text.encode())
                    equal = compact(other_text)==compact(text)
                    row['compared_pdf_originals'].append({'url':pdf_url,'original_sha256':other_hash,
                        'text_sha256':hashlib.sha256(other_text.encode()).hexdigest(),
                        'compact_text_sha256':hashlib.sha256(compact(other_text).encode()).hexdigest(),
                        'page_count':other_manifest['page_count'],
                        'whitespace_ignored_fulltext_equal':equal})
                    if not equal:
                        raise ValueError('同名PDF正文与所选原件有差异，不自动选版')
                row['uncompared_alternative_urls'] = [link for link in alternatives if link not in pdf_urls]
        row['phase'] = 'store_roundtrip'
        provenance = {'publisher':sample['issuer'], 'original_url':row.get('attachment_url',sample['url']),
                      'original_sha256':digest, 'source_format':extension.lstrip('.'),
                      'source_dates':{}, 'document_number':None,
                      'pages':[{key:page[key] for key in ('page','start','end')}
                               for page in pdf_manifest['pages']] if pdf_manifest else []}
        if not is_rule_site:
            provenance['uncompared_alternative_urls'] = row['uncompared_alternative_urls']
        if row.get('compared_pdf_originals'):
            provenance['compared_pdf_originals'] = row['compared_pdf_originals']
        version = store.add(law_id='jilin:'+sample['id'], title=sample['title'], text=text,
                            source_url=sample['url'], region=region, provenance=provenance,
                            locator=f'固定地方样本正文；原件SHA256={digest}；未经法律效力和完整性审核')
        stored = store.detail(version)
        if pdf_manifest:
            row['pdf_page_count'] = pdf_manifest['page_count']
        row.update(status='ingested_quarantine' if stored['review_state']=='quarantine' else 'reused_published',
                   version_id=version, region=region, text_sha256=stored['sha256'],
                   characters=len(text), review_state=stored['review_state'], legal_review_performed=False)
    except Exception:
        row['error'] = '本阶段来源、格式、身份或存储校验未通过；已落盘证据以文件为准，未取得或未保存的响应不声称留存，不自动降级核验'
    return row


def run_samples(root, samples, reader):
    root = Path(root)
    if (not 1 <= len(samples) <= 20 or len({x['id'] for x in samples}) != len(samples)
            or any(not re.fullmatch('[0-9]{1,12}', x['id']) for x in samples)):
        raise ValueError('固定样本ID或20份上限不符合')
    for sample in samples:
        allowed_url(sample['url'])
        if sample['kind'] not in ('government_rule','local_regulation','administrative_norm'):
            raise ValueError('未审定的资料类型')
        region_code(sample['region_name'], sample['issuer'])
    verification = root / 'verification'
    verification.mkdir(parents=True, exist_ok=True)
    with (verification / 'jilin-samples.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'ok':False, 'complete':False, 'status':'locked'}
        report = {'at':stamp(), 'complete':False, 'ok':False, 'planned':len(samples), 'results':[],
                  'attempt_finished':False, 'failed':0,
                  'originals_acquired':0,'ingested':0,'human_approved_this_run':0}
        reader.evidence_root = root / 'data/jilin-samples/responses'
        path = verification / 'jilin-samples-latest.json'
        atomic_write(path, encode(report))
        store = LegalStore(root / 'data/legal.sqlite3')
        try:
            for sample in samples:
                row = ingest_sample(root, sample, reader, store)
                report['results'].append(row)
                report['originals_acquired'] += row['original_acquired']
                report['ingested'] += row['status'] in ('ingested_quarantine','reused_published')
                report['failed'] += row['status']=='failed'
                atomic_write(path, encode(report))
        finally:
            store.close()
        report.update(complete=report['ingested']==len(samples), ok=report['ingested']==len(samples),
                      attempt_finished=True, finished_at=stamp())
        atomic_write(path, encode(report))
        return report
