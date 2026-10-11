"""Real loopback MCP acceptance; does not call upstream or modify law data."""
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def call(method, params=None):
    payload = {'jsonrpc': '2.0', 'id': 1, 'method': method}
    if params is not None:
        payload['params'] = params
    request = Request('http://127.0.0.1:18063/mcp', data=json.dumps(payload).encode(),
                      headers={'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'})
    with urlopen(request, timeout=20) as response:
        raw = response.read().decode()
    result = json.loads(next((line[6:] for line in raw.splitlines() if line.startswith('data: ')), raw))
    if 'error' in result or result.get('result', {}).get('isError'):
        raise RuntimeError(result)
    return result['result']


def tool(name, arguments=None):
    result = call('tools/call', {'name': name, 'arguments': arguments or {}})
    return result.get('structuredContent') or json.loads(result['content'][0]['text'])


def main():
    tools = call('tools/list')['tools']
    names = {item['name'] for item in tools}
    assert all(item.get('annotations', {}).get('readOnlyHint') is True for item in tools), 'read-only metadata'
    expected = {'search_law', 'get_law_fragment', 'legal_database_health',
                'search_public_corpus', 'get_public_corpus_article', 'public_corpus_inventory',
                'get_law_article'}
    assert expected <= names
    inventory = tool('public_corpus_inventory')
    assert inventory['available'] and inventory['law_versions'] > 0
    results = {}
    for label, query, title in [('civil', '民事主体的人身权利', '民法典'),
                                ('labor', '劳动报酬', '劳动合同法'),
                                ('short_chinese', '抚养', '民法典')]:
        result = tool('search_public_corpus', {'query': query, 'law_title': title, 'limit': 2})
        assert result['results'], label
        assert all(row['review_state'] == 'unverified_mirror' for row in result['results'])
        results[label] = result
    row = results['civil']['results'][0]
    fragment = tool('get_public_corpus_article', {'law_id': row['law_id'], 'article': row['article']})
    assert fragment['results'] and fragment['results'][0]['source_urls']
    acceptance = json.loads((ROOT / 'verification/civil-code-article-acceptance.json').read_text())
    official_articles = []
    for label in ('第一条', '第一百零一条', '第一千零一条', '第一千二百六十条'):
        article = tool('get_law_article', {'version_id': acceptance['version_id'], 'article': label})
        assert article['found'] and article['article_count'] == 1260
        assert article['review_state'] == 'quarantine' and not article['legal_applicability_verified']
        original = tool('get_law_fragment', {'version_id': acceptance['version_id'],
                                            'offset': article['start'], 'length': article['total_length']})
        assert article['text'] == original['text'], label
        official_articles.append(article)
    assert tool('search_law', {'query': '民法典','include_quarantine':False})['results'] == [], '未人工复核不等于已审核'
    available = tool('search_law', {'query':'民法典'})['results']
    assert available and all(row['citation']['review_at_use_required'] for row in available)
    health = tool('legal_database_health')
    assert health['integrity'] == 'ok'
    report = {'at': datetime.now(timezone.utc).isoformat(), 'passed': True,
              'tool_names': sorted(names), 'inventory': inventory, 'queries': results,
              'fragment_round_trip': True,
              'official_article_round_trips': official_articles, 'health': health,
              'note': '实际MCP调用通过；不是三个Skill的模型行为验收，也不是法律完整性验收。'}
    (ROOT / 'verification/shared-library-smoke.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'law_versions': inventory['law_versions'],
                      'text_units': inventory['text_units'], 'tool_names': sorted(names)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
