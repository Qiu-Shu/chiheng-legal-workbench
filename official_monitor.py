"""Fixed-original change watch. Never imports or mutates the legal database."""
import asyncio
import portable_lock as fcntl
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

FIELDS = ('sxx', 'gbrq', 'sxrq', 'zdjgName', 'flxz')


def stamp():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()


def atomic_write(path, payload):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_bytes(payload)
    temporary.replace(path)


def validate_targets(root, targets):
    if not targets or len(targets) > 21:
        raise ValueError('固定清单必须为1至21份')
    seen = set()
    for target in targets:
        law_id = target['law_id']
        path = (root / target['original_path']).resolve()
        metadata = target['metadata']
        if (not re.fullmatch('[0-9a-f]{32}', law_id) or law_id in seen
                or not target['title'] or not path.is_relative_to(root.resolve())
                or path.suffix not in ('.doc', '.docx')
                or not path.is_file() or path.stat().st_size > 10_000_000
                or hashlib.sha256(path.read_bytes()).hexdigest() != target['original_sha256']
                or set(metadata) != set(FIELDS)
                or any(value is not None and not isinstance(value, (str, int)) for value in metadata.values())):
            raise ValueError('固定基线身份、路径、哈希或字段无效')
        seen.add(law_id)


async def run_checks(root, targets, fetch, *, timeout=240):
    root = Path(root)
    validate_targets(root, targets)
    verification = root / 'verification'
    verification.mkdir(parents=True, exist_ok=True)
    report_path = verification / 'official-monitor-latest.json'
    with (verification / 'official-monitor.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'ok': False, 'complete': False, 'status': 'locked'}
        previous = json.loads(report_path.read_text()) if report_path.exists() else {}
        prior = {row['law_id']: row for row in previous.get('results', [])}
        rows = []
        for target in targets:
            old = prior.get(target['law_id'], {})
            rows.append({'law_id': target['law_id'], 'title': target['title'], 'status': 'not_checked',
                         'last_success': old.get('last_success'),
                         'pending_snapshots': list(old.get('pending_snapshots', []))})
        report = {'schema_version': 1, 'at': stamp(), 'complete': False, 'ok': False,
                  'scope': '固定已收录原件；不发现新ID、不审核、不入库、不发布', 'results': rows}
        atomic_write(report_path, encode(report))
        deadline = asyncio.get_running_loop().time() + timeout
        for target, row in zip(targets, rows):
            row['last_attempt'] = stamp()
            try:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TimeoutError()
                payload, metadata = await asyncio.wait_for(fetch(target), min(45, remaining))
                if not payload or len(payload) > 10_000_000 or set(metadata) != set(FIELDS):
                    raise ValueError('返回数据无效')
                digest = hashlib.sha256(payload).hexdigest()
                changes = {key: {'before': target['metadata'][key], 'after': metadata[key]}
                           for key in FIELDS if target['metadata'][key] != metadata[key]}
                changed = digest != target['original_sha256'] or bool(changes)
                if changed:
                    observation = {'law_id': target['law_id'], 'title': target['title'],
                                   'original_sha256': digest, 'metadata': metadata,
                                   'baseline_sha256': target['original_sha256'],
                                   'metadata_changes': changes, 'review_state': 'pending'}
                    snapshot_id = hashlib.sha256(encode(observation)).hexdigest()
                    folder = root / 'data/official-monitor' / target['law_id'] / snapshot_id
                    relative = str(folder.relative_to(root))
                    if relative not in row['pending_snapshots']:
                        row['pending_snapshots'].append(relative)
                    # Journal the alert before writing files: a crash must not hide
                    # a detected change even if the remote returns to baseline.
                    atomic_write(report_path, encode(report))
                    folder.mkdir(parents=True, exist_ok=True)
                    for name, content in [('original' + Path(target['original_path']).suffix, payload),
                                          ('observation.json', encode(observation))]:
                        path = folder / name
                        if path.exists():
                            if path.read_bytes() != content:
                                raise ValueError('快照冲突，拒绝覆盖')
                        else:
                            atomic_write(path, content)
                row.update(status='changed_pending_review' if changed else 'unchanged',
                           last_success=stamp(), observed_sha256=digest, metadata=metadata,
                           metadata_changes=changes, original_changed=digest != target['original_sha256'],
                           missing_date_fields=[key for key in ('gbrq', 'sxrq') if not metadata[key]])
            except Exception as error:
                # Never persist exception strings: HTTP errors can contain signed URLs.
                row.update(status='failed', error='检查超时' if isinstance(error, TimeoutError) else '来源、数据或本地保存失败')
            report['pending_documents'] = sum(bool(item['pending_snapshots']) for item in rows)
            atomic_write(report_path, encode(report))
        report.update(complete=True, finished_at=stamp(), ok=all(row['status'] != 'failed' for row in rows))
        atomic_write(report_path, encode(report))
        return report


def dashboard_lines(report):
    if not report:
        return ['尚未检查固定官方原件。']
    if report.get('status') == 'access_blocked':
        previous = report.get('previous_report')
        history = f'[旧报告]({previous})' if previous else '未附旧报告链接'
        return ['- 状态：access_blocked；本次未检查固定官方原件。',
                f'- 停止原因：{report.get("reason", "来源访问受限")}。',
                f'- 来源限制证据：[robots.txt]({report.get("evidence", {}).get("url", "")})。',
                f'- 历史待审变化数量本次未核对，见旧报告：{history}；不能据此判断原件未变化或待审记录为空。']
    rows = report.get('results', [])
    failed = sum(row.get('status') == 'failed' for row in rows)
    pending = sum(bool(row.get('pending_snapshots')) for row in rows)
    return ([f'- 运行异常：{report["preflight_error"]}'] if report.get('preflight_error') else []) + [
            f'- 检查开始：{report.get("at", "未知")}；本轮完成：{report.get("complete", False)}',
            f'- 范围：{len(rows)}份固定原件；失败：{failed}；有待审变化的文件：{pending}。',
            '- 仅比较固定版本原件及官方字段，不发现新ID/新法规，不代表现行有效或人工审核。',
            '- 失败不等于未变化；待审记录不随下一次成功自动清除，意外中断时快照可能待补全。详情见项目 verification/official-monitor-latest.json。']


def record_run_failure(root):
    verification = Path(root) / 'verification'
    verification.mkdir(parents=True, exist_ok=True)
    path = verification / 'official-monitor-latest.json'
    with (verification / 'official-monitor.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'ok': False, 'complete': False, 'status': 'locked'}
        report = json.loads(path.read_text()) if path.exists() else {'results': []}
        report.update(at=stamp(), ok=False, complete=False,
                      preflight_error='配置、依赖或本地运行异常；本次不能确认来源状态')
        for row in report['results']:
            row.update(status='failed', last_attempt=report['at'])
        atomic_write(path, encode(report))
        return report
