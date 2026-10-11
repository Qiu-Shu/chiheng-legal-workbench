"""Record actual local law fragments; receipts are consistency IDs, not signatures.

This calls the shared local implementation, not an external MCP transport or
official online source. A recorded fragment does not establish claim support.
"""
import hashlib
import json
import sqlite3

import legal_mcp
from mock_hearing import _json_copy, _validate_turn, append_turn, load_session


REVIEW_NOTICE = '本地法库返回已记录；命题是否获得支持、版本时效及案件适用性仍待律师核验'


def append_law_turn(case_root, turn, sources):
    """Validate all requests, retrieve fragments, then atomically append one turn."""
    if not isinstance(turn, dict) or turn.get('source_cards') != []:
        raise ValueError('append-law 的 turn 必须提供 source_cards=[]，不得传入自拟引用卡')
    if not isinstance(sources, list) or not 1 <= len(sources) <= 10:
        raise ValueError('sources 必须为 1—10 个对象的列表')
    if not isinstance(turn.get('unresolved'), list):
        raise ValueError('unresolved 必须为列表')
    for source in sources:
        if not isinstance(source, dict) or set(source) != {'claim', 'version_id', 'offset', 'length'}:
            raise ValueError('source 恰需 claim、version_id、offset、length')
        if (not isinstance(source['claim'], str) or not source['claim'].strip()
                or not isinstance(turn.get('text'), str) or source['claim'] not in turn['text']):
            raise ValueError('claim 必须非空且出现在 turn.text 中；字面绑定不代表法律支持')
        if not isinstance(source['version_id'], str) or not source['version_id'].strip():
            raise ValueError('version_id 必须为非空字符串')
        if type(source['offset']) is not int or source['offset'] < 0:
            raise ValueError('offset 必须为非 bool 非负整数')
        if type(source['length']) is not int or not 1 <= source['length'] <= 10000:
            raise ValueError('length 必须为非 bool 的 1—10000 整数')
    session = load_session(case_root)
    if session.get('schema_version') != 2 or session['completed']:
        raise ValueError('append-law 仅接受未完成的 v2 会话，旧记录只读')
    turn = _validate_turn(session, {**turn, 'unresolved': turn['unresolved'] + [REVIEW_NOTICE]},
                          strict_cards=True)
    sources = _json_copy(sources)
    for source in sources:
        arguments = {key: source[key] for key in ('version_id', 'offset', 'length')}
        try:
            result = legal_mcp.get_law_fragment(**arguments)
        except sqlite3.Error as error:
            raise ValueError('本地法库读取失败，未保存回合') from error
        if (not isinstance(result, dict) or result.get('found') is not True
                or not isinstance(result.get('text'), str) or not result['text'].strip()
                or not isinstance(result.get('citation'), dict)):
            raise ValueError('法库未返回可引用的非空正文及 citation')
        citation = result['citation']
        span = citation.get('character_range')
        if (result.get('version_id') != source['version_id']
                or citation.get('version_id') != source['version_id']
                or type(result.get('offset')) is not int or result['offset'] != source['offset']
                or not isinstance(span, dict)
                or type(span.get('start')) is not int or type(span.get('end')) is not int
                or span['start'] != source['offset']
                or span['end'] != source['offset'] + len(result['text'])
                or len(result['text']) > source['length']):
            raise ValueError('法库返回版本或正文字符范围与请求不一致')
        if result.get('availability') == 'withdrawn' or citation.get('availability') == 'withdrawn':
            raise ValueError('此版本已撤回，不得作为正常引用依据')
        card = dict(tool='get_law_fragment', arguments=arguments, result=result, claim=source['claim'])
        try:
            raw = json.dumps(card, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ValueError('本地法库返回无法编码为规范 JSON，未保存回合') from error
        card['receipt_id'] = hashlib.sha256(raw.encode('utf-8')).hexdigest()
        turn['source_cards'].append(card)
    return append_turn(case_root, turn)
