"""Local, single-user civil hearing rehearsal records; no legal retrieval or approval.

Use a dedicated private directory. File locks coordinate this module's writers;
they do not isolate tools running under the same OS account or provide multi-user
security. Source cards are retained as supplied, not independently authenticated.
The content digest detects changes without a matching recomputed digest; it is
not a signature, protection from same-account rewriting or malicious downgrade,
or a check of legal correctness. Legacy records are read-only. Rehearsal links
are portable snapshot references; loading a child does not authenticate or
require the current parent session.
"""
from contextlib import contextmanager
import portable_lock as fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

if os.name == 'nt':
    import windows_private
    import uuid

from hearing_audit import validate_audit
from hearing_tracking import NOTICE as TRACKING_NOTICE, replay_tracking


STAGES = ('issues', 'evidence', 'questions', 'debate', 'review')
PARTIES = {'plaintiff', 'defendant'}
ROLES = {'issues': PARTIES | {'moderator'}, 'evidence': PARTIES,
         'questions': PARTIES | {'moderator'}, 'debate': PARTIES, 'review': {'reviewer'}}
PACKET_FIELDS = {'case_id', 'procedure', 'our_role', 'materials', 'synthetic', 'human_review'}
TURN_FIELDS = {'case_id', 'stage', 'role', 'text', 'material_ids', 'source_cards', 'unresolved'}
METADATA = {'synthetic', 'human_review'}
MAX_MATERIAL_BYTES = 2 * 1024 * 1024


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _json_copy(value):
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise ValueError('输入必须是普通 JSON，不能包含 NaN 或自定义对象') from error


def _case_root(case_root, create=False):
    if os.name == 'nt':
        return windows_private.private_directory(case_root, create=create)
    root = Path(case_root).absolute()
    if '..' in root.parts:
        raise ValueError('case_root 不得含 ..')
    for part in (*reversed(root.parents), root):
        if part.is_symlink():
            raise ValueError('case_root 路径不得经过符号链接')
    if create and not root.exists():
        root.mkdir(mode=0o700)
    info = root.stat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('请使用权限为 0700 的专用演练目录；不会自动修改既有目录权限')
    return root


@contextmanager
def _locked(root):
    path = root / '.session.lock'
    fd = (windows_private.open_file(path, private=True, writable=True, create=True)
          if os.name == 'nt' else
          os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600))
    try:
        info = os.fstat(fd)
        if os.name != 'nt' and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                               or stat.S_IMODE(info.st_mode) != 0o600):
            raise ValueError('会话锁必须是独立的 0600 普通文件')
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _read_file(path, limit=None, private=False):
    if path.is_symlink():
        raise ValueError('不接受符号链接文件')
    fd = (windows_private.open_file(path, private=private) if os.name == 'nt' else
          os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK))
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if os.name != 'nt' and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
            raise ValueError('仅接受独立的普通文件')
        if os.name != 'nt' and private and stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError('session.json 权限必须为 0600')
        if limit is not None and info.st_size > limit:
            raise ValueError('单份材料不得超过 2MB')
        raw = stream.read() if limit is None else stream.read(limit + 1)
        if limit is not None and len(raw) > limit:
            raise ValueError('单份材料不得超过 2MB')
        return raw


def _validate_packet(root, packet):
    if not isinstance(packet, dict) or set(packet) != PACKET_FIELDS:
        raise ValueError('packet 字段缺失或包含未知字段')
    if not _text(packet['case_id']):
        raise ValueError('case_id 必须是非空字符串')
    if packet['procedure'] != 'civil_first_instance':
        raise ValueError('仅支持 civil_first_instance 民商事一审演练')
    if not _text(packet['our_role']) or packet['our_role'] not in PARTIES:
        raise ValueError('our_role 仅支持 plaintiff 或 defendant')
    if type(packet['synthetic']) is not bool or packet['human_review'] is not None:
        raise ValueError('synthetic 必须为布尔值，human_review 必须为 null')
    materials = packet['materials']
    if not isinstance(materials, list) or len(materials) > 100:
        raise ValueError('materials 必须为列表，最多 100 份')
    ids = set()
    paths = set()
    material_texts = {}
    for item in materials:
        if not isinstance(item, dict) or set(item) != {'id', 'relative_path', 'sha256'}:
            raise ValueError('材料需要 id、relative_path 和 sha256')
        if not _text(item['id']) or item['id'] in ids:
            raise ValueError('材料 ID 必须非空且唯一')
        ids.add(item['id'])
        name = item['relative_path']
        if (not _text(name) or '\\' in name or '\x00' in name
                or any(part in ('', '.', '..') for part in name.split('/'))
                or Path(name).is_absolute()
                or name.split('/')[0] in ('session.json', '.session.lock') or name in paths):
            raise ValueError('材料路径必须是案卷内唯一的相对路径，不得越界或使用会话文件')
        if os.name == 'nt':
            if (':' in name or name.split('/')[0].casefold() in ('session.json', '.session.lock')
                    or name.casefold() in {old.casefold() for old in paths}):
                raise ValueError('Windows 材料路径不得含数据流、会话文件或大小写重复路径')
            windows_private.validate_path(root / name)
        paths.add(name)
        path = root
        for part in name.split('/'):
            path = path / part
            if path.is_symlink():
                raise ValueError('材料路径不得经过符号链接')
        digest = item['sha256']
        if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('sha256 必须为 64 位小写十六进制值')
        raw = _read_file(path, MAX_MATERIAL_BYTES)
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError as error:
            raise ValueError('材料必须是 UTF-8 文本，不自动转换格式') from error
        if b'\x00' in raw:
            raise ValueError('材料必须是文本，不能包含 NUL 字节')
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('材料哈希不匹配，停止读取和追加')
        material_texts[item['id']] = text
    return material_texts


def _manifest_hash(packet):
    raw = json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _validate_focus(focus):
    if (not isinstance(focus, list) or not focus or any(not _text(item) for item in focus)
            or len(set(focus)) != len(focus)):
        raise ValueError('focus 必须是非空、无重复的非空字符串列表')


def _validate_rehearsal(link, case_id):
    if not isinstance(link, dict) or set(link) != {'case_id', 'content_sha256', 'turn_count', 'focus'}:
        raise ValueError('rehearsal_of 字段缺失或包含未知字段')
    if link['case_id'] != case_id:
        raise ValueError('rehearsal_of case_id 必须与当前会话一致')
    if (not isinstance(link['content_sha256'], str)
            or not re.fullmatch('[0-9a-f]{64}', link['content_sha256'])):
        raise ValueError('rehearsal_of content_sha256 必须为 64 位小写十六进制值')
    if type(link['turn_count']) is not int or link['turn_count'] <= 0:
        raise ValueError('rehearsal_of turn_count 必须为正整数')
    _validate_focus(link['focus'])


def _validate_turn(packet, turn, stored=False, strict_cards=False):
    optional = METADATA | ({'audit', 'tracking'} if strict_cards else set())
    if not isinstance(turn, dict) or not TURN_FIELDS <= set(turn) <= TURN_FIELDS | optional:
        raise ValueError('turn 字段缺失或包含未知字段')
    if stored and not METADATA <= set(turn):
        raise ValueError('已保存回合缺少演练标记')
    if turn['case_id'] != packet['case_id']:
        raise ValueError('回合 case_id 与当前案卷不一致')
    if (not _text(turn['stage']) or turn['stage'] not in STAGES
            or not _text(turn['role']) or turn['role'] not in ROLES[turn['stage']]):
        raise ValueError('阶段或角色不受支持')
    if not _text(turn['text']):
        raise ValueError('回合 text 必须非空')
    ids = turn['material_ids']
    known = {item['id'] for item in packet['materials']}
    if not isinstance(ids, list) or any(not _text(item) or item not in known for item in ids):
        raise ValueError('回合包含未知材料 ID')
    if not isinstance(turn['source_cards'], list):
        raise ValueError('source_cards 必须是保留工具返回内容的 JSON 列表')
    if strict_cards and any(not isinstance(card, dict) or not card
                            for card in turn['source_cards']):
        raise ValueError('v2 source_cards 每项必须是非空 JSON 对象；结构通过不代表工具认证')
    unresolved = turn['unresolved']
    if not isinstance(unresolved, list) or any(not _text(item) for item in unresolved):
        raise ValueError('unresolved 必须是非空说明组成的列表')
    if not turn['source_cards'] and not unresolved:
        raise ValueError('无引用卡时，unresolved 须说明未检索或未核实')
    if ('synthetic' in turn and (type(turn['synthetic']) is not bool
                                or turn['synthetic'] != packet['synthetic'])):
        raise ValueError('回合 synthetic 必须与会话一致')
    if turn.get('human_review') is not None:
        raise ValueError('human_review 必须为 null；不写入人工审核签名')
    row = {**_json_copy(turn), 'synthetic': packet['synthetic'], 'human_review': None}
    for field in ('audit', 'tracking'):
        if field in turn and row[field] != turn[field]:
            raise ValueError(f'{field} 必须使用原生 JSON 对象和列表，不自动转换类型')
    return row


def _advance(stage, seen, completed, turn):
    if completed:
        raise ValueError('review 已完成，不能继续追加')
    next_stage = turn['stage']
    if next_stage != stage:
        if STAGES.index(next_stage) != STAGES.index(stage) + 1:
            raise ValueError('仅可留在当前阶段或进入下一阶段，禁止跳跃或回退')
        if not ROLES[stage] <= seen:
            raise ValueError('当前阶段尚缺必要角色的回合')
        seen = set()
    return next_stage, seen | {turn['role']}, next_stage == 'review'


def _load(root):
    try:
        session = json.loads(_read_file(root / 'session.json', private=True).decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError('session.json 不是有效的 UTF-8 JSON') from error
    expected = PACKET_FIELDS | {'manifest_sha256', 'turns', 'stage', 'completed'}
    if not isinstance(session, dict):
        raise ValueError('session manifest 字段不完整或存在未知字段')
    versioned = 'schema_version' in session or 'content_sha256' in session
    if versioned:
        expected |= {'schema_version', 'content_sha256'}
        if type(session.get('schema_version')) is not int or session['schema_version'] != 2:
            raise ValueError('仅支持整数 schema_version=2 或只读旧格式')
        if 'rehearsal_of' in session:
            expected.add('rehearsal_of')
    if set(session) != expected:
        raise ValueError('session manifest 字段不完整或存在未知字段')
    if versioned and session['content_sha256'] != _manifest_hash(
            {key: value for key, value in session.items() if key != 'content_sha256'}):
        raise ValueError('session content 哈希不匹配')
    packet = {key: session[key] for key in PACKET_FIELDS}
    material_texts = _validate_packet(root, packet)
    if 'rehearsal_of' in session:
        _validate_rehearsal(session['rehearsal_of'], packet['case_id'])
    if session['manifest_sha256'] != _manifest_hash(packet):
        raise ValueError('session manifest 哈希不匹配')
    if not isinstance(session['turns'], list):
        raise ValueError('turns 必须为列表')
    stage, seen, completed = 'issues', set(), False
    previous_turns = []
    for turn in session['turns']:
        _validate_turn(packet, turn, stored=True, strict_cards=versioned)
        validate_audit(turn, material_texts, previous_turns)
        stage, seen, completed = _advance(stage, seen, completed, turn)
        previous_turns.append(turn)
    replay_tracking(session['turns'])
    if (session['stage'] != stage or type(session['completed']) is not bool
            or session['completed'] != completed):
        raise ValueError('会话状态与历史回合不一致')
    return session, seen, material_texts


def _write(root, session, create=False):
    raw = json.dumps(session, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if os.name == 'nt':
        temporary = root / ('.session-' + uuid.uuid4().hex + '.tmp')
        fd = windows_private.open_file(temporary, private=True, writable=True,
                                       create=True, exclusive=True)
    else:
        fd, temporary = tempfile.mkstemp(prefix='.session-', suffix='.tmp', dir=root)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if create:
            if os.name == 'nt':
                os.rename(temporary, root / 'session.json')
            else:
                os.link(temporary, root / 'session.json')
        else:
            if os.name == 'nt':
                os.close(windows_private.open_file(root / 'session.json', private=True))
            os.replace(temporary, root / 'session.json')
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def create_session(case_root, packet):
    """Create session.json without replacing existing data; packet is explicit JSON."""
    return _create_session(case_root, packet)


def create_rehearsal(case_root, packet, previous_case_root, focus):
    """Start fresh from a validated completed v2 snapshot; retain no parent path or turns."""
    _validate_focus(focus)
    previous = load_session(previous_case_root)
    if previous.get('schema_version') != 2 or not previous['completed']:
        raise ValueError('再次演练仅可关联已完成的 v2 会话')
    root = _case_root(case_root, create=True)
    if root.samefile(_case_root(previous_case_root)):
        raise ValueError('再次演练必须使用不同的专用目录')
    packet = _json_copy(packet)
    if not isinstance(packet, dict) or any(packet.get(field) != previous[field]
            for field in ('case_id', 'procedure', 'our_role', 'synthetic')):
        raise ValueError('新旧会话的 case_id、procedure、our_role 和 synthetic 必须一致')
    link = dict(case_id=previous['case_id'], content_sha256=previous['content_sha256'],
                turn_count=len(previous['turns']), focus=_json_copy(focus))
    return _create_session(root, packet, link)


def _create_session(case_root, packet, rehearsal_of=None):
    root = _case_root(case_root, create=True)
    packet = _json_copy(packet)
    with _locked(root):
        if os.name == 'nt':
            try:
                fd = windows_private.open_file(root / 'session.json', private=True)
            except FileNotFoundError:
                pass
            else:
                os.close(fd)
                raise FileExistsError('session.json 已存在，禁止覆盖')
        elif os.path.lexists(root / 'session.json'):
            raise FileExistsError('session.json 已存在，禁止覆盖')
        _validate_packet(root, packet)
        session = {**packet, 'manifest_sha256': _manifest_hash(packet),
                   'turns': [], 'stage': 'issues', 'completed': False, 'schema_version': 2}
        if rehearsal_of is not None:
            session['rehearsal_of'] = rehearsal_of
        session['content_sha256'] = _manifest_hash(session)
        _write(root, session, create=True)
    return session


def load_session(case_root):
    """Validate the manifest, explicit materials and complete turn history."""
    root = _case_root(case_root)
    with _locked(root):
        session, _, _ = _load(root)
    return session


def hearing_progress(case_root):
    """Return validated recorded progress, not substantive completion or approval."""
    session = load_session(case_root)
    issues = replay_tracking(session['turns'])
    return dict(case_id=session['case_id'], structural_completed=session['completed'],
                tracking_recorded=bool(issues), issues=issues, notice=TRACKING_NOTICE)


def append_turn(case_root, turn):
    """Validate and atomically append one turn while holding the session lock."""
    root = _case_root(case_root)
    with _locked(root):
        session, seen, material_texts = _load(root)
        if 'schema_version' not in session:
            raise ValueError('旧记录只读，请在另一个专用目录另建新演练；不得覆盖或追认旧会话')
        row = _validate_turn(session, turn, strict_cards=True)
        validate_audit(row, material_texts, session['turns'])
        replay_tracking(session['turns'] + [row])
        stage, _, completed = _advance(session['stage'], seen, session['completed'], row)
        session['turns'].append(row)
        session.update(stage=stage, completed=completed)
        session['content_sha256'] = _manifest_hash(
            {key: value for key, value in session.items() if key != 'content_sha256'})
        _write(root, session)
    return session
