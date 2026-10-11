"""Report actual local inventory and source observations, not legal completeness."""
import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import portable_lock as fcntl
from legal_store import LegalStore
from review_records import CASE_KINDS, SCOPES, validate_record
from scripts.probe_sources import load_sources, write_json
from local_settings import resolve_config_path

PROVINCES = dict(zip(
    'BJ TJ HE SX NM LN JL HL SH JS ZJ AH FJ JX SD HA HB HN GD GX HI CQ SC GZ YN XZ SN GS QH NX XJ'.split(),
    '北京 天津 河北 山西 内蒙古 辽宁 吉林 黑龙江 上海 江苏 浙江 安徽 福建 江西 山东 河南 湖北 湖南 广东 广西 海南 重庆 四川 贵州 云南 西藏 陕西 甘肃 青海 宁夏 新疆'.split()))


def catalog_summary(path):
    if not path.exists():
        return {'status': 'missing', 'scope': 'catalogue_only_unverified', 'notice': '尚无上游目录快照。'}
    raw = json.loads(path.read_text())
    counts = ('upstream_records', 'local_records', 'shared_ids', 'upstream_only_ids', 'local_only_ids')
    if (not isinstance(raw, dict) or raw.get('scope') != 'catalogue_only_unverified'
            or raw.get('status') not in ('updated', 'unchanged')
            or any(type(raw.get(key)) is not int or raw[key] < 0 for key in counts)
            or not isinstance(raw.get('snapshot'), str) or not raw['snapshot']
            or not isinstance(raw.get('checked_at_utc'), str)):
        raise ValueError('上游目录摘要结构损坏，不能按零条目录处理')
    if (raw['shared_ids'] + raw['upstream_only_ids'] != raw['upstream_records']
            or raw['shared_ids'] + raw['local_only_ids'] != raw['local_records']
            or datetime.fromisoformat(raw['checked_at_utc']).utcoffset() is None):
        raise ValueError('上游目录计数或检查时点不一致')
    fields = ('status', 'scope', 'checked_at_utc', 'snapshot', 'upstream_commit', 'local_sha256') + counts
    return {**{key: raw[key] for key in fields if key in raw},
            'notice': '仅为上游目录与本地索引的ID差异；不代表全文已下载、现行有效或核验通过。'}


def review_summary(path):
    counts = {'status': 'missing', 'total': 0,
        'by_reviewer_kind': {'human': 0, 'automated': 0},
        'by_scope': {scope: 0 for scope in sorted(SCOPES)},
        'by_reviewer_and_scope': {kind: {scope: 0 for scope in sorted(SCOPES)} for kind in ('human', 'automated')},
        'case_records': 0, 'by_result': {},
        'notice': '尚无核验记录；记录仅表示声明范围内的比对，不并入published。'}
    if not path.exists():
        return counts
    seen = set()
    with path.open() as source:
        fcntl.flock(source, fcntl.LOCK_SH)
        for number, line in enumerate(source, 1):
            try:
                raw = json.loads(line)
                if (not isinstance(raw, dict) or raw.get('schema_version') != 1
                        or not isinstance(raw.get('record_id'), str) or not raw['record_id']
                        or raw['record_id'] in seen or not isinstance(raw.get('recorded_at'), str)
                        or datetime.fromisoformat(raw['recorded_at']).utcoffset() is None):
                    raise ValueError('账本元数据无效或record_id重复')
                row = validate_record({key: value for key, value in raw.items()
                                       if key not in ('schema_version', 'record_id', 'recorded_at')})
            except (ValueError, TypeError) as error:
                raise ValueError(f'核验账本第{number}行损坏，不能按零记录处理：{error}') from error
            seen.add(raw['record_id'])
            counts['total'] += 1
            counts['by_reviewer_kind'][row['reviewer_kind']] += 1
            counts['by_scope'][row['scope']] += 1
            counts['by_reviewer_and_scope'][row['reviewer_kind']][row['scope']] += 1
            counts['case_records'] += int(row['source_kind'] in CASE_KINDS)
            counts['by_result'][row['result']] = counts['by_result'].get(row['result'], 0) + 1
    counts['status'] = 'available' if counts['total'] else 'empty'
    counts['notice'] = ('核验人类型是记录声明，未认证身份；片段、整法、案例及人工、自动分别计数。'
                        'match不代表适用性确认或审核发布；这些记录不并入published。')
    return counts


def build_report(*, store, sources, health, targets):
    inventory = [dict(row) for row in store.db.execute('''SELECT region, review_state,
        count(*) AS versions, count(DISTINCT law_id) AS documents
        FROM versions GROUP BY region, review_state ORDER BY region, review_state''')]
    regions = sorted({row['region'] for row in inventory})
    provinces = {PROVINCES.get(region.split('-')[1]) for region in regions if '-' in region}
    provinces.discard(None)
    law_ids = {row[0] for row in store.db.execute('SELECT DISTINCT law_id FROM versions')}
    source_ids = {row['source_id'] for row in sources}
    current_health = [row for row in health if row['source_id'] in source_ids]
    observed_categories = sorted({source['category'] for source in sources
        if source['source_id'] in law_ids and source.get('category')})
    missing_provinces = [name for name in targets.get('regions', []) if name not in provinces]
    missing_categories = [name for name in targets.get('source_categories', []) if name not in observed_categories]
    states = Counter(row['state'] for row in current_health)
    unprobed = sorted(source_ids - {row['source_id'] for row in current_health})
    gaps = ['已存文档和入口连通不证明法律全文、时效、版本或领域覆盖完整；覆盖总量分母尚未建立。']
    if missing_provinces:
        gaps.append(f'{len(missing_provinces)}个目标省级地区未存本地文档')
    if missing_categories:
        gaps.append(f'{len(missing_categories)}类目标来源暂无可关联的已存文档')
    if any(row.get('transport_security') == 'unencrypted' for row in current_health):
        gaps.append('存在HTTP明文观察；不能据此提升来源权威性或完整性。')
    return {**store.health(), 'at': datetime.now(timezone.utc).isoformat(),
        'coverage_complete': False,
        'scope': '配置来源健康、SQLite完整性、实际文档地域和审核状态盘点',
        'inventory': inventory,
        'sources': {'registered': len(sources), 'enabled': sum(row.get('enabled', True) for row in sources),
            'reachable': states['quarantined'], 'states': dict(states), 'unprobed': unprobed,
            'verified_tls': sum(row.get('transport_security') == 'verified_tls' and row['state'] == 'quarantined' for row in current_health),
            'unencrypted_observations': sum(row.get('transport_security') == 'unencrypted' and row['state'] == 'quarantined' for row in current_health),
            'observations': current_health},
        'coverage': {'stored_distinct_documents': len(law_ids), 'regions_with_stored_documents': regions,
            'province_targets': len(targets.get('regions', [])),
            'provinces_with_stored_documents': sorted(provinces),
            'province_targets_without_documents': missing_provinces,
            'category_targets': targets.get('source_categories', []),
            'observed_categories': observed_categories,
            'categories_without_linked_documents': missing_categories},
        'gaps': gaps}


def main(kind='integrity', *, root=ROOT):
    store = LegalStore(root / 'data/legal.sqlite3', readonly=True)
    try:
        health_path = root / 'verification/source-probes.json'
        health = json.loads(health_path.read_text()) if health_path.exists() else []
        targets = yaml.safe_load((root / 'config/coverage-targets.yaml').read_text())
        report = build_report(store=store, sources=load_sources(root), health=health, targets=targets)
        report['upstream_catalog'] = catalog_summary(root / 'data/upstream-catalog/latest.json')
        report['review_records'] = review_summary(root / 'data/review-records.jsonl')
        library = root / 'config/shared-library.json'
        if library.exists():
            from shared_corpus import PublicCorpus
            corpus = PublicCorpus(resolve_config_path(library, json.loads(library.read_text())['corpus_path']))
            report['shared_offline_corpus'] = corpus.inventory()
        report['kind'] = kind
        report['checks'] = {'sqlite_quick_check': report['integrity'], 'lawyer_review_performed': False,
                            'source_health_refreshed_by_report': False}
        name = 'coverage-monthly' if kind == 'monthly-coverage' else 'integrity'
        write_json(root / f'verification/{name}-latest.json', report)
        if kind == 'monthly-coverage':
            stamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H%M%SZ')
            write_json(root / f'verification/monthly/{stamp}.json', report)
        print(json.dumps(report, ensure_ascii=False))
        return report
    finally:
        store.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--kind', choices=('integrity', 'monthly-coverage'), default='integrity')
    args = parser.parse_args()
    result = main(args.kind)
    raise SystemExit(0 if result['integrity'] == 'ok' else 1)
