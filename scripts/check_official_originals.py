"""Check only the frozen set of known public originals; never ingest or approve."""
import asyncio
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from official_monitor import FIELDS, run_checks, record_run_failure
from scripts.ingest_basic_laws import TREASURY, TARGETS, SUPPORTING_TARGETS, LEGACY_DOC_ID, public_object_url
from local_settings import require_treasury
from official_access import FLK_ACCESS_BLOCK, record_access_block


async def read_bounded(response, limit, *, check_status=True):
    if check_status:
        response.raise_for_status()
    if response.headers.get('content-encoding', 'identity').lower() != 'identity':
        raise ValueError('不接受压缩传输，避免解压超限')
    if int(response.headers.get('content-length', '0')) > limit:
        raise ValueError('响应超过限制')
    payload = bytearray()
    async for chunk in response.aiter_bytes(chunk_size=65_536):
        if len(payload) + len(chunk) > limit:
            raise ValueError('响应超过限制')
        payload.extend(chunk)
    return bytes(payload)


class BoundedAPI:
    """Reuse installed FlkClient session/rate limit, adding monitor-only size limits."""
    def __init__(self, upstream):
        self.upstream = upstream

    async def get(self, path):
        await self.upstream._rate_limit()
        async with self.upstream._get_client().stream('GET', path,
                headers={'Accept-Encoding': 'identity'}) as response:
            data = json.loads(await read_bounded(response, 2_000_000))
        if data.get('code') != 200:
            raise ValueError('官方接口状态异常')
        return data


async def fetch_original(target, api, downloader):
    # This dedicated monitor runs sequentially. Suppress library HTTP debug/info
    # output during requests: both httpx and nested httpcore logs can expose URL queries.
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        return await _fetch_original(target, api, downloader)
    finally:
        logging.disable(previous)


async def _fetch_original(target, api, downloader):
    law_id = target['law_id']
    detail = (await api.get(f'search/flfgDetails?bbbs={law_id}'))['data']
    if detail.get('bbbs') != law_id or detail.get('title') != target['title']:
        raise ValueError('官方身份或标题不匹配')
    if any(key not in detail or (detail[key] is not None and not isinstance(detail[key], (str, int)))
           for key in FIELDS):
        raise ValueError('官方字段缺失或结构异常')
    metadata = {key: detail[key] for key in FIELDS}
    expected = detail['ossFile']['ossWordPath']
    legacy = law_id == LEGACY_DOC_ID and expected.endswith('.doc')
    # Format switches are not silently renamed or converted by a monitoring job.
    if Path(expected).suffix != Path(target['original_path']).suffix:
        raise ValueError('原件格式变化，需人工检查')
    url = (await api.get(f'download/pc?bbbs={law_id}&format=docx'))['data']['url']
    public_object_url(url, expected, allow_legacy_doc=legacy)
    async with downloader.stream('GET', url, headers={'Accept-Encoding': 'identity'}) as response:
        payload = await read_bounded(response, 10_000_000)
    magic = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1' if legacy else b'PK\x03\x04'
    if not payload.startswith(magic):
        raise ValueError('响应不是预期文档容器')
    return bytes(payload), metadata


async def main():
    try:
        return await check_known_originals()
    except Exception:
        if FLK_ACCESS_BLOCK:
            raise
        return record_run_failure(ROOT)


async def check_known_originals():
    if FLK_ACCESS_BLOCK:
        return record_access_block(ROOT, 'official-monitor-latest.json')
    targets = json.loads((ROOT / 'config/official-monitor.json').read_text())['targets']
    allowed = dict((law_id, title) for title, law_id in TARGETS + SUPPORTING_TARGETS)
    allowed['ff808081729d1efe01729d50b5c500bf'] = '中华人民共和国民法典'
    if len(targets) != 21 or {row['law_id']: row['title'] for row in targets} != allowed:
        raise ValueError('固定21份监测范围不匹配')
    treasury = require_treasury(TREASURY)
    sys.path.insert(0, str(treasury / '.python-deps'))
    sys.path.insert(0, str(treasury / 'sources/legal-tools/国家法律法规数据库MCP/scripts'))
    import httpx
    from client import FlkClient
    api = FlkClient()
    try:
        async with httpx.AsyncClient(timeout=30, verify=True, follow_redirects=False) as downloader:
            async def fetch(target):
                return await fetch_original(target, BoundedAPI(api), downloader)
            return await run_checks(ROOT, targets, fetch)
    finally:
        await api.close()


if __name__ == '__main__':
    try:
        result = asyncio.run(main())
        print(json.dumps(result if result.get('status') == 'access_blocked' else
                         {'ok': result['ok'], 'complete': result['complete'],
                          'documents': len(result.get('results', [])),
                          'report': 'verification/official-monitor-latest.json'}, ensure_ascii=False))
        raise SystemExit(0 if result['ok'] else 1)
    except Exception:
        print('官方原件监测未完成：配置、依赖或本地运行异常；不得视为检查成功。')
        raise SystemExit(1)
