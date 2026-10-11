"""One 100-row discovery batch; partial batches remain retryable, never ingested."""
import asyncio
import hashlib
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from law_discovery import run_discovery, save_evidence
from scripts.ingest_basic_laws import keep_original
from scripts.check_official_originals import TREASURY, read_bounded
from local_settings import require_treasury
from official_access import FLK_ACCESS_BLOCK, record_access_block


async def main():
    if FLK_ACCESS_BLOCK:
        return record_access_block(ROOT, 'law-discovery-latest.json')
    # Dependency setup is inside the callback so even import/config failure is reported.
    api = None
    async def fetch(window, page, size):
        nonlocal api
        treasury = require_treasury(TREASURY)
        sys.path.insert(0, str(treasury / '.python-deps'))
        sys.path.insert(0, str(treasury / 'sources/legal-tools/国家法律法规数据库MCP/scripts'))
        from client import FlkClient
        from models import FlkHighSearchInput, HighSearchCondition
        api = api or FlkClient()
        body = FlkHighSearchInput(conditions=[HighSearchCondition(field_name='gbrq',
                 values=[window['start'], window['end']])], page_num=page, page_size=size).to_api_dict()
        # Official advanced-search frontend index-CAiCIcGW.js exposes this exact
        # publication-date order. Date ties can still drift; validation remains.
        body['orderByParam'] = {'order':'gbrq','sort':'DESC'}
        previous = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        try:
            await api._rate_limit()
            async with api._get_client().stream('POST', 'highSearch/highSearch', json=body,
                    headers={'Accept-Encoding': 'identity'}) as response:
                raw = await read_bounded(response, 2_000_000, check_status=False)
                digest = hashlib.sha256(raw).hexdigest()
                folder = ROOT / 'data/discovery/http'
                folder.mkdir(parents=True,exist_ok=True)
                keep_original(folder/(digest+'.bin'),raw)
                save_evidence(ROOT,'http-metadata',{'query':body,'status':response.status_code,
                              'response_sha256':digest,'endpoint':'https://flk.npc.gov.cn/law-search/highSearch/highSearch'})
                response.raise_for_status()
                return json.loads(raw)
        finally:
            logging.disable(previous)
    try:
        return await run_discovery(ROOT, fetch, today=datetime.now(ZoneInfo('Asia/Shanghai')).date(),
                                   query_profile='gbrq_DESC_v1')
    finally:
        if api is not None:
            await api.close()


if __name__ == '__main__':
    result = asyncio.run(main())
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result['ok'] else 2)
