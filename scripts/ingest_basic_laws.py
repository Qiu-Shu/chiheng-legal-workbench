"""Manually invoked fixed official batches; reuse installed client, no crawling or approval."""
import argparse
import asyncio
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from legal_store import LegalStore
from official_docx import article_labels, check_articles, extract_docx, normalize_headings
from law_articles import HEADING
from legacy_doc import convert_legacy_doc, SOFFICE
from local_settings import require_treasury, resolve_soffice
from official_access import FLK_ACCESS_BLOCK, record_access_block

# require_treasury resolves machine settings only after the access guard.
TREASURY = None
TARGETS = [
    ('中华人民共和国民事诉讼法', 'ff8081818a21dc13018b425303b7086d'),
    ('中华人民共和国刑事诉讼法', 'ff8080816f135f46016f1d1b81b01351'),
    ('中华人民共和国行政诉讼法', '2c909fdd678bf17901678bf858550a0f'),
    ('中华人民共和国劳动合同法', '2c909fdd678bf17901678bf74d7106b3'),
    ('中华人民共和国公司法', 'ff8081818c9108eb018cb6922f750c07'),
    ('中华人民共和国行政复议法', 'ff8081818a21e6c3018a508d491a0c98'),
]
SUPPORTING_TARGETS = [
    ('最高人民法院关于适用《中华人民共和国民事诉讼法》的解释', 'ff80818181cdceb30181d801c31c4070'),
    ('最高人民法院关于适用《中华人民共和国民事诉讼法》执行程序若干问题的解释', 'ff80818179f5d2480179fa4c0ccb0492'),
    ('最高人民法院关于适用《中华人民共和国民事诉讼法》审判监督程序若干问题的解释', 'ff808181799def980179b1ab569c1b33'),
    ('最高人民法院关于适用《中华人民共和国刑事诉讼法》的解释', 'ff8081817b969375017b9b912cd009dc'),
    ('最高人民法院关于适用《中华人民共和国行政诉讼法》的解释', '2c90e5ba65c68cf70167f29d0e604ec4'),
    ('中华人民共和国劳动合同法实施条例', 'ff8080816f3cbb3c016f40927caf049c'),
    ('最高人民法院关于审理劳动争议案件适用法律问题的解释（一）', 'ff80808177e75f88017800739d621b12'),
    ('最高人民法院关于审理劳动争议案件适用法律问题的解释（二）', 'ff80818198a7eafa0199329bcc11687f'),
    ('最高人民法院关于适用《中华人民共和国公司法》时间效力的若干规定', 'ff8081819150444501916e8c37764524'),
    ('国务院关于实施《中华人民共和国公司法》注册资本登记管理制度的规定', 'ff808181907350630190dd6d975c6c01'),
    ('最高人民法院关于《中华人民共和国公司法》第八十八条第一款不溯及适用的批复', 'ff808181927f1276019448a29dca7d34'),
    ('中华人民共和国行政复议法实施条例', 'ff8081819dfcb526019e0ac7ce234ece'),
    ('最高人民法院关于适用《中华人民共和国民法典》时间效力的若干规定', 'ff80808177e757ac017800561d541abb'),
    ('最高人民法院关于适用《中华人民共和国民法典》合同编通则若干问题的解释', 'ff8081818c24e05b018c814e6de45ab5'),
]
# These fixed official details were observed with content=null; keep the lower
# validation scope explicit. This is not a fallback for a mismatching catalog.
MISSING_CATALOG_TARGETS = {
    'ff808181799def980179b1ab569c1b33',
    'ff8081819150444501916e8c37764524',
    'ff808181907350630190dd6d975c6c01',
    'ff80818181cdceb30181d801c31c4070',
    'ff80818179f5d2480179fa4c0ccb0492',
    'ff8081817b969375017b9b912cd009dc',
    '2c90e5ba65c68cf70167f29d0e604ec4',
    'ff8080816f3cbb3c016f40927caf049c',
    'ff80808177e75f88017800739d621b12',
    'ff80818198a7eafa0199329bcc11687f',
    'ff8081819dfcb526019e0ac7ce234ece',
    'ff80808177e757ac017800561d541abb',
    'ff8081818c24e05b018c814e6de45ab5',
}
LEGACY_DOC_ID = 'ff808181799def980179b1ab569c1b33'
UNNUMBERED_REPLY_ID = 'ff808181927f1276019448a29dca7d34'


def check_document(text, catalog, law_id):
    if law_id == UNNUMBERED_REPLY_ID:
        if catalog is not None or any(match.group('article') for match in HEADING.finditer(text)):
            raise ValueError('已登记的不分条批复结构发生变化，需重新核验')
        return {'structure': 'unnumbered_document', 'article_count': 0, 'articles': [],
                'official_labels_match': False, 'catalog_status': 'missing',
                'unassigned_body_content': None, 'consecutive_numbering_checked': False,
                'legal_completeness_reviewed': False, 'legal_applicability_verified': False}
    return check_articles(text, article_labels(catalog), allow_missing_catalog=(
        law_id in MISSING_CATALOG_TARGETS and catalog is None))


def batch_targets(name):
    if name == 'basic-laws':
        return TARGETS
    if name == 'supporting-rules':
        return SUPPORTING_TARGETS
    raise ValueError('仅支持已登记的固定批次')


def keep_original(path, payload):
    previous = None
    if path.exists():
        previous = path.read_bytes()
        if previous == payload:
            return
        # Only a strict prefix is recoverable as a potentially interrupted write.
        # Preserve that evidence; unrelated content is never replaced.
        if not payload.startswith(previous):
            raise ValueError('同名原件内容不同，拒绝覆盖')
        backup = path.with_name(path.name + '.incomplete-' + hashlib.sha256(previous).hexdigest())
        keep_original(backup, previous)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.'+path.name, delete=False) as output:
            temporary = Path(output.name)
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        if path.exists():
            if previous is None or path.read_bytes() != previous:
                raise ValueError('原件在保存期间变化，拒绝覆盖')
            temporary.replace(path)
        else:
            os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def public_object_url(url, expected_path, *, allow_legacy_doc=False):
    try:
        parsed = urlsplit(url)
    except ValueError:
        raise ValueError('官方下载地址无法解析，停止') from None
    if (parsed.scheme != 'https' or parsed.netloc not in ('flkoss.obs-bj2.cucloud.cn', 'flkoss.obs-bj2.cucloud.cn:443')
            or parsed.path != '/' + expected_path
            or not (expected_path.endswith('.docx') or (allow_legacy_doc and expected_path.endswith('.doc')))):
        raise ValueError('下载地址不符合官方HTTPS对象及详情路径，停止')
    return parsed._replace(query='', fragment='').geturl()


def storage_result(stored):
    if stored['review_state'] not in ('quarantine', 'published'):
        raise ValueError('未知数据库审核状态，停止报告成功')
    return {'status': 'ingested_quarantine' if stored['review_state'] == 'quarantine' else 'reused_published',
            'version_id': stored['version_id'], 'review_state': stored['review_state'],
            'legal_applicability_verified': False}


def source_metadata(row):
    official = row['official_metadata']
    return {'publisher':official.get('zdjgName'),
            'original_url':row['object_url_without_signature'],
            'original_sha256':row.get('original_sha256',row.get('docx_sha256')),
            'source_format':row.get('source_format','docx'), 'document_number':None,
            'source_dates':{'published_on':official.get('gbrq'), 'effective_from':official.get('sxrq')},
            'pages':[]}


async def main(batch_name='basic-laws'):
    targets = batch_targets(batch_name)
    if FLK_ACCESS_BLOCK:
        return record_access_block(ROOT, f'{batch_name}-ingestion-latest.json')
    treasury = require_treasury(TREASURY)
    # Same client and dependency directory as the already installed official MCP wrapper.
    sys.path[:0] = [str(treasury / '.python-deps'),
                   str(treasury / 'sources/legal-tools/国家法律法规数据库MCP/scripts')]
    import httpx
    from client import FlkClient
    api = FlkClient()
    store = LegalStore(ROOT / 'data/legal.sqlite3')
    report = {'at': datetime.now(timezone.utc).isoformat(), 'purpose': 'personal_noncommercial_learning',
              'batch': batch_name,
              'scope': f'固定{len(targets)}份文件官方详情、DOCX和条号机械核对；非人工审核', 'results': []}
    try:
        async with httpx.AsyncClient(verify=True, follow_redirects=False, timeout=30.0) as downloader:
            for title, law_id in targets:
                row = {'title': title, 'law_id': law_id, 'status': 'failed',
                       'source_url': f'https://flk.npc.gov.cn/detail?id={law_id}',
                       'checked_at': datetime.now(timezone.utc).isoformat()}
                try:
                    row['phase'] = 'official_detail'
                    detail = (await api.get(f'search/flfgDetails?bbbs={law_id}'))['data']
                    if detail['bbbs'] != law_id or detail['title'] != title or detail['sxx'] != 3:
                        raise ValueError('官方身份/标题/状态发生变化，需重新选版本')
                    official = {key: detail.get(key) for key in
                                ('bbbs', 'title', 'gbrq', 'sxrq', 'sxx', 'zdjgName', 'flxz')}
                    row['official_metadata'] = official
                    row['official_catalog_missing'] = detail['content'] is None
                    expected_path = detail['ossFile']['ossWordPath']
                    row['phase'] = 'official_download'
                    response = (await api.get(f'download/pc?bbbs={law_id}&format=docx'))['data']
                    signed_url = response['url']
                    legacy = law_id == LEGACY_DOC_ID and expected_path.endswith('.doc')
                    row['object_url_without_signature'] = public_object_url(signed_url, expected_path, allow_legacy_doc=legacy)
                    async with downloader.stream('GET', signed_url) as remote:
                        remote.raise_for_status()
                        payload = bytearray()
                        async for chunk in remote.aiter_bytes():
                            payload.extend(chunk)
                            if len(payload) > 10_000_000:
                                raise ValueError('原件超过10MB，停止自动处理')
                    payload = bytes(payload)
                    original_hash = hashlib.sha256(payload).hexdigest()
                    folder = ROOT / 'data/official-basic-laws' / law_id / original_hash
                    folder.mkdir(parents=True, exist_ok=True)
                    original_name = 'original.doc' if legacy else 'original.docx'
                    keep_original(folder / original_name, payload)
                    row.update({'original_sha256': original_hash, 'original_file': original_name,
                                'source_format': 'doc' if legacy else 'docx',
                                'artifact_directory': str(folder.relative_to(ROOT)), 'downloaded': True})
                    direct_text = None
                    if legacy:
                        row['phase'] = 'legacy_conversion'
                        converted, direct_text = convert_legacy_doc(payload)
                        # Converter ZIP metadata may vary. Reuse the first retained derivative.
                        derived = folder / 'converted-libreoffice.docx'
                        if not derived.exists():
                            keep_original(derived, converted)
                        payload = derived.read_bytes()
                        keep_original(folder / 'direct-libreoffice.txt', direct_text.encode())
                        row['conversion'] = {'tool': str(resolve_soffice(SOFFICE)), 'derived_file': 'converted-libreoffice.docx',
                                             'direct_text_sha256': hashlib.sha256(direct_text.encode()).hexdigest(),
                                             'independent_converter': False}
                    docx_hash = hashlib.sha256(payload).hexdigest()
                    row.update({'docx_sha256': docx_hash, 'docx_bytes': len(payload),
                                'artifact_directory': str(folder.relative_to(ROOT)), 'downloaded': True,
                                'tls_verified': True, 'signed_query_stored': False})
                    row['phase'] = 'docx_extract'
                    raw_text, extraction = extract_docx(payload, title)
                    if legacy and ''.join(raw_text.split()) != ''.join(direct_text.split()):
                        raise ValueError('旧DOC直接文字与转换DOCX文字不一致')
                    raw_name = 'raw-body-libreoffice.txt' if legacy else 'raw-body.txt'
                    body_name = 'body-libreoffice.txt' if legacy else 'body.txt'
                    row.update({'raw_text_file': raw_name, 'text_file': body_name})
                    keep_original(folder / raw_name, raw_text.encode())
                    text, changes = normalize_headings(raw_text, detail['content'])
                    labels = article_labels(detail['content'])
                    row['phase'] = 'article_check'
                    check = check_document(text, detail['content'], law_id)
                    if any(text[span['start']:span['end']] != raw_text[span['start']:span['end']]
                           for span in check['articles']):
                        raise ValueError('标题格式处理改变条文正文，拒绝入库')
                    text_hash = hashlib.sha256(text.encode()).hexdigest()
                    keep_original(folder / body_name, text.encode())
                    row.update({'text_sha256': text_hash, 'text_characters': len(text),
                                'raw_text_sha256': hashlib.sha256(raw_text.encode()).hexdigest(),
                                'heading_normalization': changes, 'official_article_labels': labels,
                                'article_text_unchanged_by_normalization': True,
                                'extraction': extraction, 'mechanical_check': check})
                    locator = f'官方DOCX正文；原件SHA256={docx_hash}；法律审核待完成'
                    if legacy:
                        locator = f'官方DOC原件经本机LibreOffice分区转换；原件SHA256={original_hash}；法律审核待完成'
                    if law_id == UNNUMBERED_REPLY_ID:
                        locator += '；不分条批复，按全文位置读取，不造条号'
                    if changes:
                        locator += '；官方目录匹配的标题软换行规范化；原始抽取另存raw-body.txt'
                    row['phase'] = 'store_round_trip'
                    version = store.add(law_id='npc:' + law_id, title=title, text=text,
                                        source_url=row['source_url'], region='CN',
                                        locator=locator)
                    stored = store.detail(version)
                    if stored['text'] != text or stored['sha256'] != text_hash:
                        raise ValueError('入库回读与原文不一致')
                    store.set_provenance(version, source_metadata(row))
                    row.update(storage_result(stored))
                    row['phase'] = 'metadata_write'
                    capture = folder / ('libreoffice-capture.json' if legacy else 'first-capture.json')
                    if not capture.exists():
                        keep_original(capture, (json.dumps(row, ensure_ascii=False, indent=2) + '\n').encode())
                    row['phase'] = 'completed'
                except Exception as error:
                    # Remote errors can embed signed URLs; never persist exception strings from clients.
                    row['error_type'] = type(error).__name__
                    row['status'] = 'failed'
                    row['error'] = '该阶段检查失败；异常原文未持久化，避免临时签名泄露'
                report['results'].append(row)
                target = ROOT / f'verification/{batch_name}-ingestion-latest.json'
                temporary = target.with_suffix('.tmp')
                temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
                temporary.replace(target)
                print(json.dumps({key: row[key] for key in ('title', 'status', 'error') if key in row}, ensure_ascii=False), flush=True)
                await asyncio.sleep(1)
    finally:
        await api.close()
        store.close()
    return 0 if all(row['status'] in ('ingested_quarantine', 'reused_published') for row in report['results']) else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch', choices=('basic-laws', 'supporting-rules'), default='basic-laws')
    result = asyncio.run(main(parser.parse_args().batch))
    if isinstance(result, dict):
        print(json.dumps(result, ensure_ascii=False))
        raise SystemExit(0 if result['ok'] else 1)
    raise SystemExit(result)
