"""Refresh public-law catalogue metadata only; publish snapshots after validation."""
import argparse
import base64
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from local_settings import resolve_config_path

API = 'https://api.github.com/repos/lawtext/law-flk-vol1'


def fetch_json(url):
    # Use the platform TLS/proxy setup; no shell or TLS bypass is used.
    curl = '/usr/bin/curl'
    if sys.platform == 'win32':
        system = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/curl.exe'
        curl = str(system) if system.is_file() else shutil.which('curl.exe')
        if not curl or not Path(curl).is_file():
            raise ValueError('Windows curl.exe is unavailable; catalogue was not changed')
    result = subprocess.run([curl, '--fail', '--silent', '--show-error',
                             '--connect-timeout', '10', '--max-time', '25', '--retry', '1',
                             '--header', 'Accept: application/vnd.github+json',
                             '--user-agent', 'Menglu-Personal-Law-Catalogue', url],
                            capture_output=True, check=True, timeout=60)
    return json.loads(result.stdout)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def validate_records(document):
    rows = document.get('data') if isinstance(document, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError('上游目录为空或结构异常，保留最后良好快照')
    ids = []
    for row in rows:
        if (not isinstance(row, dict) or not re.fullmatch(r'[0-9a-fA-F]{32}', str(row.get('bbbs', '')))
                or not isinstance(row.get('title'), str) or not row['title'].strip()):
            raise ValueError('上游目录包含无效 ID 或标题')
        ids.append(row['bbbs'])
    if len(ids) != len(set(ids)) or document.get('stats', {}).get('total') != len(rows):
        raise ValueError('上游目录重复 ID 或统计数量不一致')
    return {row['bbbs']: row for row in rows}


def download_blob(item, fetch):
    blob = fetch(API + '/git/blobs/' + item['sha'])
    if blob.get('encoding') != 'base64':
        raise ValueError('GitHub 文件编码异常')
    raw = base64.b64decode(''.join(blob['content'].split()), validate=True)
    actual = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    if actual != item['sha'] or blob.get('sha') != actual or len(raw) != item['size']:
        raise ValueError('GitHub 文件长度或 Git blob 哈希不符')
    return raw


def refresh(config, output_root, fetch_json=fetch_json):
    config, output_root = Path(config), Path(output_root)
    settings = json.loads(config.read_text(encoding='utf-8'))
    local_path = resolve_config_path(config, settings['corpus_path'])
    local_raw = local_path.read_bytes()
    local = json.loads(local_raw).get('laws')
    if not isinstance(local, dict) or not local:
        raise ValueError('本地索引为空或结构异常')
    local_hash = sha256(local_raw)
    commit = fetch_json(API + '/commits/main')
    commit_sha = commit.get('sha', '')
    if not re.fullmatch(r'[0-9a-f]{40}', commit_sha):
        raise ValueError('GitHub 提交 ID 异常')
    latest_path = output_root / 'latest.json'
    previous = json.loads(latest_path.read_text()) if latest_path.exists() else None
    old_ids = None
    if previous:
        old_snapshot = output_root / previous['snapshot']
        old_manifest = json.loads((old_snapshot / 'manifest.json').read_text())
        for name, item in old_manifest['files'].items():
            if sha256((old_snapshot / name).read_bytes()) != item['sha256']:
                raise ValueError('已有快照校验失败，请检查文件完整性')
        old_ids = set(validate_records(json.loads((old_snapshot / 'records.json').read_text())))
        if previous['upstream_commit'] == commit_sha and previous['local_sha256'] == local_hash:
            return {**previous, 'status': 'unchanged', 'new_upstream_ids': [], 'removed_upstream_ids': []}

    listing = fetch_json(API + '/contents/?ref=' + commit_sha)
    if not isinstance(listing, list):
        raise ValueError('GitHub 文件目录结构异常')
    items = {row['name']: row for row in listing}
    readmes = sorted(name for name in items if name.lower() in ('readme', 'readme.md', 'readme.rst', 'readme.txt'))
    names = ['records.json', 'LOG.md'] + readmes
    if any(name not in items or items[name].get('type') != 'file' for name in names):
        raise ValueError('上游缺少必需目录文件')
    raw_files = {name: download_blob(items[name], fetch_json) for name in names}
    document = json.loads(raw_files['records.json'])
    upstream = validate_records(document)
    up_ids, local_ids = set(upstream), set(local)
    missing, local_only = sorted(up_ids - local_ids), sorted(local_ids - up_ids)
    summary = {
        'status': 'updated', 'scope': 'catalogue_only_unverified',
        'checked_at_utc': datetime.now(timezone.utc).isoformat(),
        'upstream_commit': commit_sha, 'local_sha256': local_hash,
        'upstream_records': len(upstream), 'local_records': len(local),
        'shared_ids': len(up_ids & local_ids), 'upstream_only_ids': len(missing),
        'local_only_ids': len(local_only), 'baseline_created': old_ids is None,
        'new_upstream_ids': sorted(up_ids - old_ids) if old_ids is not None else [],
        'removed_upstream_ids': sorted(old_ids - up_ids) if old_ids is not None else [],
        'snapshot': 'snapshots/' + commit_sha + '-' + local_hash[:12],
    }
    gap = {'summary': summary, 'upstream_only': [upstream[key] for key in missing],
           'local_only': [{'id': key, 'title': local[key].get('title')} for key in local_only]}
    output_root.mkdir(parents=True, exist_ok=True)
    target = output_root / summary['snapshot']
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.catalog-', dir=output_root) as temporary:
        stage = Path(temporary) / 'snapshot'
        stage.mkdir()
        for name, raw in raw_files.items():
            (stage / name).write_bytes(raw)
        write_json(stage / 'github-commit.json', commit)
        write_json(stage / 'github-root.json', listing)
        write_json(stage / 'catalog-gap.json', gap)
        with (stage / 'catalog-gap.csv').open('w', encoding='utf-8-sig', newline='') as output:
            writer = csv.writer(output)
            writer.writerow(['comparison', 'id', 'title', 'category', 'publication_date', 'effective_date', 'raw_sxx', 'raw_my_status'])
            for key in missing:
                row = upstream[key]
                writer.writerow(['upstream_only', key, row['title'], row.get('flxz'), row.get('gbrq'), row.get('sxrq'), row.get('sxx'), row.get('my_status')])
            for key in local_only:
                writer.writerow(['local_only', key, local[key].get('title'), '', '', '', '', ''])
        manifest = {
            'upstream_commit': commit_sha, 'upstream_commit_date_utc': commit['commit']['committer']['date'],
            'repository': 'https://github.com/lawtext/law-flk-vol1',
            'local_source': str(local_path), 'local_sha256': local_hash,
            'upstream_update_label': document.get('update'), 'upstream_reported_stats': document.get('stats'),
            'readme_present': bool(readmes), 'scope': 'catalogue_only_unverified', 'files': {},
        }
        for path in sorted(stage.iterdir()):
            raw = path.read_bytes()
            entry = {'bytes': len(raw), 'sha256': sha256(raw)}
            if path.name in raw_files:
                entry.update(git_blob_sha1=items[path.name]['sha'], git_blob_verified=True,
                             source_url=API + '/git/blobs/' + items[path.name]['sha'])
            manifest['files'][path.name] = entry
        write_json(stage / 'manifest.json', manifest)
        if target.exists():
            raise ValueError('目标快照已存在但未被当前指针引用，请先核查')
        stage.replace(target)
        pointer = Path(temporary) / 'latest.json'
        write_json(pointer, summary)
        pointer.replace(latest_path)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, default=ROOT / 'config/shared-library.json')
    parser.add_argument('--output-root', type=Path, default=ROOT / 'data/upstream-catalog')
    args = parser.parse_args()
    try:
        result = refresh(args.config, args.output_root)
    except Exception as error:
        print(json.dumps({'status': 'failed', 'error': str(error), 'last_good_snapshot_preserved': True}, ensure_ascii=False))
        raise SystemExit(1)
    print(json.dumps(result, ensure_ascii=False))
