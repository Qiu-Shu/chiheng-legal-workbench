"""Collect non-secret reports and code packages; never package law corpus or accounts."""
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT.parents[1] / 'outputs'
FILES = {
    ROOT/'docs/multiple-pdf-progress.md': '长春多PDF核对与剩余4项进度.md',
    ROOT/'verification/multiple-pdf-acceptance.json': '多PDF比较与39版本最新验收.json',
    ROOT/'verification/multiple-pdf-final-replay.json': '最终原子入库16份重放验收.json',
    ROOT/'verification/multiple-pdf-code-review.md': '多PDF与原子入库独立复核.md',
    ROOT/'docs/attachment-recovery-progress.md': '地方附件恢复与最新39版本进度.md',
    ROOT/'verification/attachment-recovery-acceptance.json': '39版本全文与引用卡验收.json',
    ROOT/'verification/attachment-preflight.json': '地方18个PDF预检结果.json',
    ROOT/'verification/attachment-recovery-code-review.md': '地方附件恢复独立复核.md',
    ROOT/'docs/direct-ingest-pdf-progress.md': '直接入库与引用时审阅进度.md',
    ROOT/'verification/direct-ingest-acceptance.json': '38版本全文与引用卡验收.json',
    ROOT/'verification/source-metadata-backfill.json': '既有国家法源来源字段补充.json',
    ROOT/'docs/jilin-rule-layout-progress.md': '吉林规章结构修复与剩余缺口报告.md',
    ROOT/'verification/jilin-rule-layout-acceptance.json': '吉林五份规章正文覆盖验收.json',
    ROOT/'docs/law-discovery-jilin-progress.md': '新法规发现与吉林地方原文续建报告.md',
    ROOT/'verification/law-discovery-latest.json': '官方新法规候选发现状态.json',
    ROOT/'verification/jilin-samples-latest.json': '吉林20份样本逐项采集结果.json',
    ROOT/'verification/jilin-samples-acceptance.json': '吉林地方正文共享检索验收.json',
    ROOT/'verification/discovery-scheduler-acceptance.json': '新法规发现调度链实测.json',
    ROOT/'docs/official-monitor-progress.md': '已收录官方原件自动监测验收报告.md',
    ROOT/'verification/official-monitor-latest.json': '21份官方原件最新监测.json',
    ROOT/'verification/official-monitor-scheduler-acceptance.json': '官方原件监测调度实测.json',
    ROOT/'verification/official-baseline-audit-2026-09-27.json': '官方资料基线核对.json',
    ROOT.parent/'local-legal-inventory.md': '本地法律资源盘点.md',
    ROOT.parent/'github-reuse-review.md': 'GitHub复用审查.md',
    ROOT/'docs/shared-library-contract.md': '共享法律库架构与使用.md',
    ROOT/'docs/source-scheduler-update.md': '来源连接与自动更新验收.md',
    ROOT/'docs/upstream-catalog-gap.md': '全国法规目录差集说明.md',
    ROOT/'docs/chatgpt-private-connection.md': 'ChatGPT私有接入状态.md',
    ROOT/'docs/official-download-diagnosis.md': '官方原件下载与分条修复.md',
    ROOT/'docs/official-article-progress.md': '民法典官方分条与共享检索续建报告.md',
    ROOT/'verification/civil-code-article-acceptance.json': '民法典1260条机械验收.json',
    ROOT/'docs/basic-laws-progress.md': '六部基础法官方原件入库报告.md',
    ROOT/'verification/basic-laws-acceptance.json': '六部基础法机械与接口验收.json',
    ROOT/'verification/basic-laws-official-search.json': '六部基础法官方检索与配套线索.json',
    ROOT/'docs/supporting-rules-progress.md': '配套司法解释与行政法规续建报告.md',
    ROOT/'docs/supporting-format-recovery.md': '四份配套文件格式处理与入库报告.md',
    ROOT/'verification/supporting-rules-acceptance.json': '配套规则机械与接口验收.json',
    ROOT/'verification/supporting-rules-ingestion-latest.json': '配套规则原件与入库记录.json',
    ROOT/'verification/acceptance-latest.json': '共享法库工程验收.json',
    ROOT/'verification/shared-library-smoke.json': '共享法库MCP实测.json',
    ROOT/'verification/coverage-monthly-latest.json': '共享法库覆盖月报.json',
    ROOT/'data/upstream-catalog/lawtext-2026-09-27/catalog-gap.csv': '全国目录318项候选缺口.csv',
}


def main():
    OUTPUT.mkdir(exist_ok=True)
    for source, name in FILES.items():
        if not source.is_file():
            raise FileNotFoundError(source)
        shutil.copy2(source, OUTPUT/name)
    files = list(FILES.values()) + [
        'cn-litigation-redteam-experimental-2026-09-27.zip', 'chiheng-legal-plugin-2026-09-27.zip',
        'menglu-legal-treasury-updated-skill-2026-09-27.zip', 'menglu-shared-library-source-2026-09-27.zip']
    manifest = {'at': datetime.now(timezone.utc).isoformat(), 'purpose': 'personal_noncommercial_learning',
                'excludes': ['credentials', 'private_matter_files', 'full_legal_corpus', 'virtualenv'],
                'files': {name: {'sha256': hashlib.sha256((OUTPUT/name).read_bytes()).hexdigest(),
                                 'bytes': (OUTPUT/name).stat().st_size} for name in files}}
    (OUTPUT/'共享法库交付清单.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'files': len(files), 'manifest': str(OUTPUT/'共享法库交付清单.json')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
