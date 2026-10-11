"""Read back every actually ingested fixed sample through the shared loopback MCP."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from legal_store import LegalStore
from official_monitor import atomic_write, encode, stamp
from scripts.smoke_shared_library import tool


def main():
    capture = json.loads((ROOT/'verification/jilin-samples-latest.json').read_text())
    store = LegalStore(ROOT/'data/legal.sqlite3', readonly=True)
    results = []
    try:
        before = store.health()
        for item in capture['results']:
            if not item.get('version_id'):
                continue
            stored = store.detail(item['version_id'])
            original = ROOT/item['original_path']
            assert hashlib.sha256(original.read_bytes()).hexdigest()==item['original_sha256']
            assert (original.parent/'body.txt').read_text()==stored['text']
            fragments = []
            for offset in range(0,len(stored['text']),10000):
                fragment = tool('get_law_fragment',{'version_id':item['version_id'],'offset':offset,'length':10000})
                assert fragment['found'] and fragment['review_state']=='quarantine'
                assert fragment['source_url']==item['url'] and fragment['region']==item['region']
                fragments.append(fragment['text'])
            assert ''.join(fragments)==stored['text']
            assert hashlib.sha256(stored['text'].encode()).hexdigest()==item['text_sha256']
            approved = tool('search_law',{'query':item['title'],'include_quarantine':False})['results']
            assert not approved, '未经人工复核资料不得伪装成已审核'
            quarantined = tool('search_law',{'query':item['title']})['results']
            assert item['version_id'] in {x['version_id'] for x in quarantined}
            assert fragment['citation']['source_url']==item['url']
            assert fragment['citation']['review_at_use_required']
            results.append({'id':item['id'],'title':item['title'],'version_id':item['version_id'],
                            'region':item['region'],'characters':len(stored['text']),
                            'fragment_calls':len(fragments),'original_and_text_hash_match':True})
        assert len(results)==capture['ingested'] and results
        assert store.health()==before and before['published']==0
        report = {'at':stamp(),'passed':True,'sample_versions_verified':len(results),
                  'fragment_calls':sum(x['fragment_calls'] for x in results),'health':before,
                  'results':results,'human_law_review_completed':False,
                  'scope':'原件哈希、保存正文、SQLite及共享MCP全文回读一致；非法律适用、视觉或全省覆盖验收'}
        atomic_write(ROOT/'verification/jilin-samples-acceptance.json',encode(report))
        print(json.dumps({k:v for k,v in report.items() if k!='results'},ensure_ascii=False))
    finally:
        store.close()


if __name__=='__main__':
    main()
