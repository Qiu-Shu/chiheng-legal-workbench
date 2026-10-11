"""Observed source restrictions for this project's national-library entry points."""
import hashlib
import json
from pathlib import Path

from official_monitor import atomic_write, encode, stamp


FLK_ACCESS_BLOCK = {
    'domain': 'flk.npc.gov.cn',
    'reason': '国家法律法规数据库 robots.txt 明确禁止任何自动化采集，'
              '且 User-agent: * / Disallow: /；本项目停止该来源的自动读取。',
    'evidence': {
        'url': 'https://flk.npc.gov.cn/robots.txt',
        'observed_on': '2026-09-28',
        'observations': 2,
        'http_status': 200,
        'content_type': 'text/plain',
        'redirected': False,
        'sha256': '69af1c653106e97435ff756e86a8baefd9876c656fe5828fe692744d48fafe9d',
        'local_record': 'verification/national-robots-observation-2026-09-28.json',
    },
}


def record_access_block(root, report_name):
    """Archive prior evidence before recording the block; do not touch source state."""
    root = Path(root)
    path = root / 'verification' / report_name
    report = {'ok': False, 'complete': False, 'partial': True, 'status': 'access_blocked',
              'report_persisted': True,
              **FLK_ACCESS_BLOCK, 'results': [],
              'scope': '仅阻断本项目国家库自动入口；离线解析及其他来源任务不受此限制影响。'}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            payload = path.read_bytes()
            try:
                previous = json.loads(payload)
            except (ValueError, UnicodeError, RecursionError):
                previous = None
            if isinstance(previous, dict):
                comparable = {key: value for key, value in previous.items()
                              if key not in ('at', 'previous_report')}
                if comparable == report:
                    return previous
            archive = path.parent / 'access-blocked-history' / (
                path.stem + '-' + hashlib.sha256(payload).hexdigest() + '.json')
            archive.parent.mkdir(parents=True, exist_ok=True)
            if archive.exists():
                if archive.read_bytes() != payload:
                    raise ValueError('旧报告备份内容冲突，拒绝覆盖')
            else:
                atomic_write(archive, payload)
            report['previous_report'] = str(archive.relative_to(root))
        report['at'] = stamp()
        atomic_write(path, encode(report))
        return report
    except (OSError, ValueError):
        report.update(report_persisted=False,
                      report_error='报告保存失败；旧报告未覆盖，本次来源访问仍被阻断。')
    report['at'] = stamp()
    return report
