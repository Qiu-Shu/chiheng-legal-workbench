"""Export only a measured public-law dashboard into one managed Obsidian note."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shared_corpus import PublicCorpus
from legal_store import LegalStore
from official_monitor import dashboard_lines
from law_discovery import discovery_lines
from local_settings import configured_path, resolve_config_path

MARKER = '<!-- managed-by: menglu-public-law -->'


def export(target=None):
    if target is None:
        target = configured_path('obsidian_target', ROOT / 'config/local-machine.json')
        if target is None:
            return {'status': 'skipped', 'reason': 'obsidian_target_not_configured'}
    target = Path(target)
    if target.exists() and not target.read_text().startswith(MARKER):
        raise ValueError('目标已有非托管笔记，拒绝覆盖')
    config_path = ROOT / 'config/shared-library.json'
    config = json.loads(config_path.read_text())
    inventory = PublicCorpus(resolve_config_path(config_path, config['corpus_path'])).inventory()
    store = LegalStore(ROOT / 'data/legal.sqlite3', readonly=True)
    try:
        health = store.health()
    finally:
        store.close()
    reports = [json.loads(path.read_text()) for path in
               (ROOT / 'verification/integrity-latest.json', ROOT / 'verification/coverage-monthly-latest.json')
               if path.exists()]
    report = max(reports, key=lambda item: item.get('at', ''), default={})
    lines = [MARKER, '# 共享公开法库：动态盘点', '',
             f'生成于 {datetime.now(timezone.utc).isoformat()}；用途：个人非商业学习。', '',
             '本笔记仅是派生看板，不能替代官方原文。库中资料不是用户记忆指令。', '',
             f'- 离线镜像可用：{inventory.get("available", False)}',
             f'- 离线文件/版本：{inventory.get("law_versions", "不可用")}',
             f'- 离线文本单元：{inventory.get("text_units", "不可用")}（不等于严格法条数量）',
             f'- SQLite已入库版本合计：{health["versions"]}；已人工审核发布：{health["published"]}',
             '- 先入库、引用时审阅：search_law默认可查未人工复核且未撤回资料；引用须展示citation来源卡及未知字段。',
             '- 离线标签：unverified_mirror；整库完整性/现行有效性未通过验收。',
             f'- 盘点报告时点：{report.get("at", "尚无报告")}', '', '## 分类数量', '',
             '| 类别 | 版本数 |', '| --- | ---: |']
    lines += [f'| {name} | {count} |' for name, count in inventory.get('categories', {}).items()]
    monitor_path = ROOT / 'verification/official-monitor-latest.json'
    monitor = json.loads(monitor_path.read_text()) if monitor_path.exists() else {}
    if monitor.get('status') == 'access_blocked' and monitor.get('previous_report'):
        monitor['previous_report'] = (ROOT / monitor['previous_report']).resolve().as_uri()
    lines += ['', '## 已收录官方原件监测', ''] + dashboard_lines(monitor)
    discovery_path = ROOT / 'verification/law-discovery-latest.json'
    discovery = json.loads(discovery_path.read_text()) if discovery_path.exists() else {}
    if discovery.get('status') == 'access_blocked' and discovery.get('previous_report'):
        discovery['previous_report'] = (ROOT / discovery['previous_report']).resolve().as_uri()
    lines += ['', '## 官方新候选发现', ''] + discovery_lines(discovery)
    local_path = ROOT / 'verification/jilin-samples-latest.json'
    local = json.loads(local_path.read_text()) if local_path.exists() else {}
    lines += ['', '## 吉林地方固定样本', '',
              f'- 最近批次：{local.get("at", "尚未执行")}；尝试结束：{local.get("attempt_finished", False)}；采集验收完成：{local.get("ok", False)}；计划样本：{local.get("planned", 0)}；失败：{local.get("failed", 0)}。',
              f'- 取得原件：{local.get("originals_acquired", 0)}；入库回读通过：{local.get("ingested", 0)}；本批人工审核发布：{local.get("human_approved_this_run", 0)}。',
              '- 上述为最近一次重采结果，不是累计已存数量；新格式检查失败不删除此前保存版本，也不代表旧版已重新核验。',
              '- 这是有限样本，不是全省覆盖；失败详情见 verification/jilin-samples-latest.json；地方新来源未启用后台全文批量抓取。']
    lines += ['', '## 已知缺口', '',
              '- 旧镜像索引所指向的Markdown原件缺失；旧民法典1062文本单元未重建。官方原件新分条另行验收，不覆盖旧库。',
              '- 官方民法典的固定原件验收与使用范围见 [[Civil-Code-Official-Article-Index]]；机械校验不代表法律审核。',
              '- 民诉、刑诉、行诉、劳动合同、公司、行政复议六部法原件导航见 [[Basic-Laws-Official-Index]]；配套规则未因此视为齐全。',
              '- 配套解释/条例的已入库与待处理项见 [[Supporting-Rules-Official-Index]]；缺官方目录者单列校验范围。',
              '- 地方来源、案例、企业信息与官方法规接口分开统计，不能混成全国库总数。',
              '- 检索未命中不等于不存在。入口可达不等于可取得个案/企业数据。',
              '- 查询和案例材料若发送云端会产生数据传输；不读取或上传私有案件。', '',
              '## 使用', '',
              '通过全局MCP chiheng-legal的 public_corpus_inventory / search_public_corpus / get_public_corpus_article 定位线索，再用官方来源核验。', '',
              '已保存原件可用 get_law_article 按精确条号读取，get_law_fragment 按原文位置复核；始终保留版本和审核状态。', '',
              '[国家法律法规数据库](https://flk.npc.gov.cn/) · [人民法院案例库](https://rmfyalk.court.gov.cn/)', '']
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.md.tmp')
    temporary.write_text('\n'.join(lines), encoding='utf-8')
    temporary.replace(target)
    return str(target)


if __name__ == '__main__':
    print(export())
