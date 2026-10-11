# 新法规发现与吉林样本实施计划

> 当前会话使用executing-plans逐项实施；用户已确认范围，不重复询问执行方式。先测试再实现，最后一次独立只读复核。

目标：官方近90日候选分页发现、吉林地方原文最多20份试采、共享看板如实报告。
架构：复用FlkClient与有界响应读取；独立候选状态不写法律SQLite。地方复用Scrapling和现有存储/格式工具；采集失败保持隔离，不审批。Python3.12，SQLite，既有调度。
规范：../specs/2026-09-27-law-discovery-jilin-design.md。

## 任务1：候选发现

文件：law_discovery.py、scripts/discover_official_laws.py、tests/test_law_discovery.py。

- [x] 写入并运行失败测试：100条上限、跨轮窗口冻结、上一页重验、日期越界、空字段、页数/总数不符、重复ID、来源变化、错误脱敏、锁。`python -m unittest discover -s tests -p test_law_discovery.py`预期先失败。
- [x] 实现`async run_discovery(root, fetch_page, today, page_size=50, max_rows=100, timeout=240)`，fetch_page(window,page,size)返回官方JSON。每页验证日期及必需字段后写不可变页快照，状态原子替换；下轮先重验已读末页，发生漂移不推进并标异常。完成窗口前冻结起止日；完整以后再次滚动90日重扫；目录保持去重。
- [x] 生产入口复用官方高级搜索模型构造参数、FlkClient限速/会话及read_bounded，POST只到固定官方路径。来源排序未经证实不自造排序参数。
- [x] 测试变绿并运行全套；真实运行一批，若过滤异常不得绕过校验。

核心验收示例：`first=await run_discovery(...,max_rows=100)`，源总数150时`partial is True`且`last_completed_window`为空；第二轮检查上一页后继续，结果去重150条方可完成。

## 任务2：吉林样本

文件：jilin_sources.py、scripts/ingest_jilin_samples.py、config/jilin-samples.json、tests/test_jilin_sources.py。

- [x] 只读观察官方页面和前端明示的数据端点，固定允许主机/路径；查询robots，403/挑战/TLS失败停止。无登陆、无审查建议提交。
- [x] 先写失败测试：正文缺失/附件未取得不能入库、标题/制定主体不符、地域区分、网页导航不混正文、去重、robots拒绝、HTTP失败、审核状态保持、原件哈希及回读。
- [x] 根据实际返回的官方结构实现最小提取。只能使用已观察正文选择器/字段，缺失即失败，不泛化抓全文。每份保存完整原响应、提取正文及来源元数据；最多20份，逐份报告。
- [x] 运行真实样本批次与回读验证，遇文档转换问题保留原件并单列，不猜条号。省/长春/松原与法规/规章/规范性文件覆盖有缺口则明确列出。

验收例：同一原件复跑版本数不增加；不同地域不会默认归入CN-JL；`store.health()['published']==0`，查不到正文时`status!='ingested_quarantine'`。

## 任务3：调度、看板、交付

文件：scripts/scheduled_update.py、scripts/export_obsidian_library.py、tests/test_scheduler.py及交付脚本、docs/law-discovery-jilin-progress.md。

- [x] 先测试national候选部分完成/失败仍更新看板但任务非成功；月度原流程不改。
- [x] 仅把候选发现接入national，地方本批不加后台全文抓取。看板分别显示范围、候选、原件、入库和人工审核数量。
- [x] 全套测试、真实工具回读、独立复核、修复回归、交付哈希验证；只写小范围项目记忆。

## 接口预检与决策

- 候选状态→调度：partial返回非零以沿用退避续跑；不能误记已完成。来源若永久异常报告失败，不缩减窗口伪造成功。
- 地方报告→看板：成功计数只取数据库实际回读；候选/下载/入库/发布不可混算。
- Ruling: 无Git仓库，沿用已授权现有目录，保留本轮计划和交付校验，不创建/删除Git工作区 — 不改动用户历史结构 — 代价是无Git级隔离和提交回滚。

## 执行记录

本记录随真实测试更新，不以计划替代验收。

### 2026-09-27 实施及中断恢复记录

- Task 1: 实现并实测。候选发现17项测试通过；初次缺模块及新增异常场景均观察RED后变GREEN。当前冻结窗口2026-06-29至09-27，1198为来源声称总数，当前扫描100条，历史候选194，partial=true，完成游标为空。此项完成是有界流程实施，不是窗口全量扫描完成。
- Task 2: 实现并试采。地方12项测试通过；20份样本逐项尝试，17份原件、10份正文入库、10份失败。10份全文均真实MCP回读一致，0自动发布。不能将尝试结束视为20份采集验收完成。
- Task 3: 调度/看板实现；national五步骤实际执行码0/0/2/0/0，候选未完成使整体非成功，但21原件检查与看板继续执行。沿用原自动任务，非新建定时任务。中断恢复后再次执行全量测试和共享回读；交付哈希校验结果另补。
- 全套162项工程测试通过；50行为/人工法律审核未完成。独立复核仅一次，不进行重复审查。

### 复核修复记录

- Final: fixed 省政府规章制定机关/来源类型可伪造 — test_government_issuer_and_kind_cannot_be_forged RED→GREEN。
- Final: fixed 分页持续变化永久卡游标 — test_drift_archives_scan_and_recovers_same_window_next_run RED→GREEN；另测最多两次重扫后明确要求处理。
- Final: fixed 全失败仍标完成及错误响应证据缺失 — test_failure_is_not_completed_and_http_evidence_is_saved RED→GREEN；test_invalid_page_is_saved_before_validation RED→GREEN。
- Final: fixed 不完整文件无法恢复 — test_partial_original_is_preserved_and_recovers_atomically RED→GREEN，先保存残片，不覆盖无关冲突。
- 复核两项Minor重评为Important：相等预算永久不能前进、保存失败统计虚增，直接影响数据进度真实性；分别以test_budget_must_allow_recheck_and_forward_progress、test_state_write_failure_reports_only_persisted_progress RED→GREEN修复。
- 实际规章模板旧标题被注释：test_actual_rule_template_uses_visible_title_and_issuer RED→GREEN，只支持观察过的可见正文模板；其余结构不绕过校验。
- Final: minor (deferred): 无。功能/来源/法律验收缺口仍按报告保留，不冒充小问题已解决。

### 决策记录（含审查未判断事项）

- Ruling: 官网高级检索前端明确提供gbrq/DESC后采用该排序，保存旧扫描再重扫 — 默认顺序已实测漂移，不猜自定义排序字段 — 同日排序仍不稳定，重扫可能仍无法完成。
- Final: Ruling: 真实来源/数据库采集结果由主实施者运行与回读补证 — 独立审查只用临时目录与模拟响应 — 没有第二人独立核验来源结果的保证。
- Final: Ruling: 法律效力、地域适用及50项行为验收继续待审 — 工程回读不是法律意见 — 不能直接声称正式生产法律验收完成。
- Final: Ruling: 未观察文档结构、转换和中文渲染不作完整性承诺，严格失败保留原件 — 避免静默漏文 — 可能少收资料，须后续专项验收。
- Final: Ruling: 只重验末页不证明所有历史页稳定，保持分页完整性限制 — 远端未提供固定快照承诺 — 早期页面变化仍可能漏检。
- Final: Ruling: 既有存储/调度/解析只作本轮相关检查及工程回归，不扩称全系统审计 — 本次审查范围有限 — 仍可能有未覆盖的旧模块问题。
- 收尾技能适配既有无Git决定：不显示虚构合并/推送选项，不删除工程、计划或证据；保留本地交付，不公开发布。
- 中断后实际接口复验报SQLite无法打开，直接只读正常。旧PID44766引用runtime.previous，重启已登记只读服务到PID51757后10全文与7工具通过；没有改库、改权限或改服务配置。只记录旧进程/环境关联，不断言已证实底层权限原因。最新162测试仍通过。
- Task 3: 收尾完成。33个交付文件SHA256/大小核对通过，4个ZIP CRC及新增源码/报告和排除数据库/原件目录检查通过，证据verification/discovery-delivery-acceptance.json。Obsidian托管看板及两个项目小摘要/更新/缺口/验收记录已按真实33份、162测试、194历史候选/100当前扫描更新。未删工程、未公开发布、未声明全国覆盖完成。
