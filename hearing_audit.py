"""Validate optional rehearsal snapshots; no fact finding or approval authority.

Material text must come from the session's existing manifest/hash validation.
Offsets count Python string characters in the decoded UTF-8 text.
"""


AUDIT_FIELDS = {'fact_register', 'admission_queue', 'attack_links', 'artifact_ids', 'corrections'}
FACT_FIELDS = {'fact_id', 'speaker', 'text', 'time', 'status', 'source_refs',
               'contrary_refs', 'external_use_status'}
ADMISSION_FIELDS = {'admission_id', 'text', 'fact_ids', 'purpose', 'risk',
                    'reviewer', 'decision', 'reviewed_at'}
ATTACK_FIELDS = {'attack_id', 'fact_ids', 'admission_review_ids', 'external_use_status'}
RECORD_STATUSES = {'supported_by_record', 'admitted_in_record', 'judicially_found'}
FACT_STATUSES = RECORD_STATUSES | {'alleged', 'hypothetical', 'disputed', 'unclear'}
EXTERNAL_STATUSES = {'internal_only', 'blocked'}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _fields(value, fields):
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError('audit 对象字段缺失或包含未知字段')


def _ids(values, known=None):
    if (not isinstance(values, list) or any(not _text(value) for value in values)
            or len(set(values)) != len(values)
            or (known is not None and not set(values) <= known)):
        raise ValueError('audit ID 必须为非空、唯一且已定义的字符串')
    return set(values)


def _refs(refs, material_texts, material_ids):
    if not isinstance(refs, list):
        raise ValueError('audit 证据定位必须为列表')
    for ref in refs:
        _fields(ref, {'material_id', 'start', 'end', 'quote'})
        identifier, start, end, quote = (ref[key] for key in ('material_id', 'start', 'end', 'quote'))
        if (not _text(identifier) or identifier not in material_texts
                or identifier not in material_ids):
            raise ValueError('audit 定位材料必须同时属于 manifest 和当轮 material_ids')
        text = material_texts[identifier]
        if (type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(text)
                or not isinstance(quote, str) or not quote or text[start:end] != quote):
            raise ValueError('audit 引文须与材料字符范围精确相同，范围须为非 bool 整数')


def validate_audit(turn, material_texts, previous_turns):
    """Validate one snapshot using verified material text and earlier turns."""
    if 'audit' not in turn:
        return
    audit = turn['audit']
    _fields(audit, AUDIT_FIELDS)
    if any(not isinstance(audit[key], list) for key in AUDIT_FIELDS):
        raise ValueError('audit 五个字段均须为列表')
    for key, fields in [('fact_register', FACT_FIELDS), ('admission_queue', ADMISSION_FIELDS),
                        ('attack_links', ATTACK_FIELDS)]:
        for item in audit[key]:
            _fields(item, fields)
    fact_ids = _ids([fact['fact_id'] for fact in audit['fact_register']])
    admission_ids = _ids([item['admission_id'] for item in audit['admission_queue']])
    _ids([item['attack_id'] for item in audit['attack_links']])
    material_ids = set(turn['material_ids'])
    _ids(audit['artifact_ids'], set(material_texts) & material_ids)
    for fact in audit['fact_register']:
        if (not _text(fact['speaker']) or not _text(fact['text'])
                or (fact['time'] is not None and not _text(fact['time']))
                or not _text(fact['status']) or fact['status'] not in FACT_STATUSES
                or not _text(fact['external_use_status'])
                or fact['external_use_status'] not in EXTERNAL_STATUSES):
            raise ValueError('audit 事实文本、时间或状态无效；不得标记为已批准对外使用')
        for key in ('source_refs', 'contrary_refs'):
            _refs(fact[key], material_texts, material_ids)
        if fact['status'] in RECORD_STATUSES and not fact['source_refs']:
            raise ValueError('audit 记录型事实状态必须提供 source_refs')
    for item in audit['admission_queue']:
        if (any(not _text(item[key]) for key in ('text', 'purpose', 'risk'))
                or item['text'] not in turn['text']):
            raise ValueError('audit 自认风险文本须逐字出现在当轮发言中，并说明目的与风险')
        if not _ids(item['fact_ids'], fact_ids):
            raise ValueError('audit 自认风险必须关联至少一项当轮事实')
        if any(item[key] is not None for key in ('reviewer', 'decision', 'reviewed_at')):
            raise ValueError('audit 审批字段必须为 null；尚未接入真实审批')
    for item in audit['attack_links']:
        _ids(item['fact_ids'], fact_ids)
        _ids(item['admission_review_ids'], admission_ids)
        if (not _text(item['external_use_status'])
                or item['external_use_status'] not in EXTERNAL_STATUSES
                or (item['admission_review_ids'] and item['external_use_status'] != 'blocked')):
            raise ValueError('audit 攻防关联仅限内部使用；关联自认风险时必须 blocked')
    corrected = set()
    for correction in audit['corrections']:
        _fields(correction, {'turn_index', 'reason'})
        index = correction['turn_index']
        if (type(index) is not int or not 0 <= index < len(previous_turns)
                or 'audit' not in previous_turns[index] or index in corrected
                or not _text(correction['reason'])):
            raise ValueError('audit 更正须唯一指向此前带 audit 的回合，并提供非空原因')
        corrected.add(index)
