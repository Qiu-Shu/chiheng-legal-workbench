"""Bounded reads of registered public URLs; all observations stay quarantined."""
import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from scrapling.fetchers import Fetcher

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import portable_lock as fcntl
from legal_store import LegalStore
from robots_policy import confirmed_robots

AGENT = 'ChihengLegalResearch/0.1'


def get(url):
    # Normal HTTPS verification, no impersonation, proxy rotation or challenge solving.
    return Fetcher.get(url, headers={'User-Agent': AGENT}, stealthy_headers=False,
                       verify=True, follow_redirects=False, retries=0, timeout=15)


def load_sources(root=ROOT):
    return json.loads((root / 'config/sources.json').read_text())['sources']


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def merge_health(previous, incoming):
    merged = {}
    for row in previous + incoming:
        old = merged.get(row['source_id'], {})
        result = dict(row, last_attempt=row.get('attempted_at'))
        result['last_success'] = old.get('last_success') or row.get('last_success')
        result['last_good_snapshot'] = old.get('last_good_snapshot') or row.get('last_good_snapshot')
        if row['state'] == 'quarantined':
            result['last_success'] = row['attempted_at']
            result['last_good_snapshot'] = {key: row[key] for key in
                ('url', 'resolved_url', 'sha256', 'title', 'version_id', 'transport_security') if key in row}
        merged[row['source_id']] = result
    return sorted(merged.values(), key=lambda row: row['source_id'])


def probe_source(source, *, directory, store, fetch=get, delay=5, robots_cache=None):
    robots_cache = {} if robots_cache is None else robots_cache
    row = dict(source_id=source['source_id'], url=source['url'], region=source['region'],
               attempted_at=datetime.now(timezone.utc).isoformat(), state='failed', attempts=[])
    for url in [source['url']] + source.get('fallback_urls', []):
        phase = 'fetch'
        attempt = {'url': url, 'state': 'failed'}
        row['attempts'].append(attempt)
        try:
            origin = f'{urlsplit(url).scheme}://{urlsplit(url).netloc}'
            if origin not in robots_cache:
                robots = fetch(origin + '/robots.txt')
                attempt['robots_status'] = robots.status
                try:
                    parser = confirmed_robots(robots)
                except ValueError as error:
                    row['state'] = attempt['state'] = 'manual_required'
                    attempt['error'] = str(error)
                    break
                robots_cache[origin] = parser
            if not robots_cache[origin].can_fetch(AGENT, url):
                row['state'] = attempt['state'] = 'robots_disallowed'
                break
            time.sleep(delay)
            page = fetch(url)
            row['http_status'] = attempt['http_status'] = page.status
            if page.status != 200:
                row['state'] = attempt['state'] = ('manual_required' if page.status in (401, 403, 429) else 'http_error')
                if page.status not in (404, 410, 500, 502, 503, 504):
                    break
                continue
            text = page.markdown(main_content_only=True)
            title = page.css('title::text').get() or source['source_id']
            challenge = any(word in (title + text[:500]).lower() for word in
                            ('captcha', '安全验证', '人机验证', 'access denied', 'just a moment'))
            if challenge or len(text.strip()) < 200:
                row['state'] = attempt['state'] = 'empty_or_challenge'
                break
            digest = hashlib.sha256(page.body).hexdigest()
            phase = 'storage'
            directory.mkdir(parents=True, exist_ok=True)
            (directory / (digest + '.html')).write_bytes(page.body)
            (directory / (digest + '.md')).write_text(text)
            secure = urlsplit(url).scheme == 'https'
            # Plain HTTP fallback is only a connectivity observation, never ingested as law.
            document = bool(source.get('document')) and secure
            row.update(state='quarantined', title=title, sha256=digest, characters=len(text),
                       document=document, resolved_url=url,
                       transport_security='verified_tls' if secure else 'unencrypted',
                       fallback_used=url != source['url'], authority_verified=False)
            attempt['state'] = 'quarantined'
            if document:
                row['version_id'] = store.add(law_id=source['source_id'], title=title, text=text,
                    source_url=url, locator='完整发布页；条款定位待审核', region=source['region'])
            break
        except Exception as error:
            attempt['error'] = str(error)[:800]
            row['error'] = attempt['error']
            if phase == 'storage':
                row['state'] = attempt['state'] = 'storage_error'
                break
    if row['state'] == 'quarantined':
        row.pop('error', None)
    elif row['attempts']:
        row['error'] = row['attempts'][-1].get('error', row['state'])
    return row


def main(group='all', *, root=ROOT, source_ids=None):
    verification = root / 'verification'
    verification.mkdir(parents=True, exist_ok=True)
    # Also covers direct CLI use, so manual probes cannot race scheduled probes.
    with (verification / 'source-probes.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'ok': False, 'state': 'locked', 'error': '已有来源探测运行'}
        store = LegalStore(root / 'data/legal.sqlite3')
        rows, robots_cache = [], {}
        try:
            for source in load_sources(root):
                if not source.get('enabled', True) and not source_ids:
                    continue
                if group != 'all' and source['group'] != group:
                    continue
                if source_ids and source['source_id'] not in source_ids:
                    continue
                row = probe_source(source, directory=root / 'data/quarantine', store=store,
                                   robots_cache=robots_cache)
                rows.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
        finally:
            store.close()
        target = verification / 'source-probes.json'
        previous = json.loads(target.read_text()) if target.exists() else []
        write_json(target, merge_health(previous, rows))
        with (verification / 'source-probe-history.jsonl').open('a') as output:
            for row in rows:
                output.write(json.dumps(row, ensure_ascii=False) + '\n')
        return {'ok': bool(rows) and all(row['state'] == 'quarantined' for row in rows),
                'attempted': len(rows), 'reachable': sum(row['state'] == 'quarantined' for row in rows),
                'unencrypted_observations': sum(row.get('transport_security') == 'unencrypted' for row in rows)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--group', choices=('all', 'national', 'local'), default='all')
    parser.add_argument('--source', action='append', help='限定登记的source_id，可重复')
    args = parser.parse_args()
    result = main(args.group, source_ids=args.source)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result['ok'] else 1)
