"""Append-only public-source review declarations; never publish source documents.

content_sha256 identifies exactly the content described by scope and locator.
match/mismatch describes that comparison, not legal applicability or court approval.
reviewer_kind is an explicit declaration; this module does not authenticate reviewers.
"""
import portable_lock as fcntl
import ipaddress
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


CASE_KINDS = {'guiding_case', 'reference_case', 'ordinary_judgment', 'typical_case'}
SOURCE_KINDS = CASE_KINDS | {
    'statute', 'judicial_interpretation', 'administrative_regulation',
    'departmental_rule', 'local_regulation', 'local_rule',
}
SCOPES = {'entire_law', 'entire_case', 'fragment'}
RESULTS = {'match', 'mismatch', 'inconclusive'}
REFERENCE_STATUSES = {'referable', 'no_longer_referable', 'not_applicable', 'unverified'}
JUDGMENT_VALIDITIES = {'effective', 'not_effective', 'revoked', 'modified',
                      'not_applicable', 'unverified'}
REQUIRED = {'source_kind', 'source_url', 'locator', 'content_sha256', 'reviewer',
            'reviewer_kind', 'checked_at', 'result', 'scope'}
CASE_FIELDS = {'case_reference_status', 'judgment_validity'}


def validate_record(record):
    """Validate a public citation and explicit conclusions, without inferring any status."""
    if not isinstance(record, dict):
        raise ValueError('记录必须是JSON对象')
    missing = REQUIRED - record.keys()
    unknown = record.keys() - REQUIRED - CASE_FIELDS
    if missing or unknown:
        raise ValueError(f'缺少字段: {sorted(missing)}；不允许字段: {sorted(unknown)}')
    if any(not isinstance(value, str) or not value.strip() for value in record.values()):
        raise ValueError('所有记录字段必须是非空字符串')
    row = {key: value.strip() for key, value in record.items()}
    enums = {'source_kind': SOURCE_KINDS, 'scope': SCOPES, 'result': RESULTS,
             'reviewer_kind': {'human', 'automated'}}
    for field, choices in enums.items():
        if row[field] not in choices:
            raise ValueError(f'{field}必须是: {", ".join(sorted(choices))}')
    is_case = row['source_kind'] in CASE_KINDS
    if is_case:
        if not CASE_FIELDS <= row.keys():
            raise ValueError('案例必须分别填写case_reference_status和judgment_validity；未知填写unverified')
        if row['case_reference_status'] not in REFERENCE_STATUSES:
            raise ValueError('case_reference_status枚举不合法')
        if row['judgment_validity'] not in JUDGMENT_VALIDITIES:
            raise ValueError('judgment_validity枚举不合法')
        if row['scope'] == 'entire_law':
            raise ValueError('案例不能使用entire_law范围')
    elif CASE_FIELDS & row.keys() or row['scope'] == 'entire_case':
        raise ValueError('非案例不能填写案例状态或使用entire_case范围')
    if not re.fullmatch(r'[0-9a-fA-F]{64}', row['content_sha256']):
        raise ValueError('content_sha256必须是对应核验范围内容的64位SHA-256')
    row['content_sha256'] = row['content_sha256'].lower()
    try:
        checked = datetime.fromisoformat(row['checked_at'])
        if checked.utcoffset() is None:
            raise ValueError
    except ValueError as error:
        raise ValueError('checked_at必须是含时区的ISO-8601时间，不自动代填核验时间') from error
    try:
        url = urlsplit(row['source_url'])
        host = url.hostname or ''
        url.port  # Validate port syntax/range without retaining it as review metadata.
    except ValueError as error:
        raise ValueError('source_url格式不合法') from error
    if (url.scheme not in ('http', 'https') or not host or url.username is not None
            or url.password is not None or any(c.isspace() for c in row['source_url'])
            or host == 'localhost' or host.endswith(('.localhost', '.local'))):
        raise ValueError('source_url须为不含登录凭证的公开HTTP(S)原文URL')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if '.' not in host:
            raise ValueError('source_url不能是本机或内网主机名')
    else:
        if not address.is_global:
            raise ValueError('source_url不能指向本机或私有网络地址')
    return row


def append_record(path, record):
    """Append one validated declaration under an exclusive process lock and fsync."""
    row = validate_record(record)
    row = {**row, 'schema_version': 1, 'record_id': str(uuid.uuid4()),
           'recorded_at': datetime.now(timezone.utc).isoformat()}
    payload = (json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n').encode('utf-8')
    ledger = Path(path)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open('a+b') as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            if stream.seek(0, os.SEEK_END):
                stream.seek(-1, os.SEEK_END)
                if stream.read(1) != b'\n':
                    raise ValueError('账本末行不完整；停止追加，保留原文件供人工检查')
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    return row
