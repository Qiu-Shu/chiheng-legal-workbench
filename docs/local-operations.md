# 持衡本机使用与实施状态

更新：2026-09-28。用途以用户最新说明为准：个人非商业学习。当前是跨Skill共享实验基础服务，全国完整资料库和全领域验收尚未完成。跨Mac迁移使用 docs/mac-migration-guide.md 和经过校验的个人数据包，不能直接复制旧 LaunchAgents 或 .venv。

## 已安装

- `scrapling-official` 官方技能，版本0.4.15；下一轮对话可发现。
- `cn-litigation-redteam` 技能，启用自动选择；可用 `$cn-litigation-redteam` 显式调用。
- Python 3.12.14 独立环境，Scrapling 0.4.15、MCP 2.2.0、PyYAML 6.0.3，具体依赖见项目 requirements.lock.txt。
- Chromium、Headless Shell、FFmpeg；静态中文、动态JS、外网三项测试通过。
- Codex MCP 名称 `chiheng-legal`，地址 `http://127.0.0.1:18063/mcp`。
- 登录自动启动与进程退出重启服务 `com.chiheng.legal-mcp`。
- 统一调度 `com.menglu.legal-update` 登录运行、每5分钟核对到期任务。Asia/Shanghai：全国周一至五06:30，吉林重点周二/五07:00，周日08:00完整性，首个周日08:00月报；实际执行可能延后最多一个轮询间隔，关机/休眠时不能运行。
- 持久状态、失败退避、防重入和错过合并补一次已实现；登录/唤醒后的调度检查补最近一期，不逐期补抓。
- Obsidian有持衡与共享法库治理索引；专用法源目录内有自动刷新的动态盘点页，不把全文放全局记忆。

## 当前数据

现存JSON镜像已只读接入：2,190个法律版本/77,809文本单元，全部unverified_mirror。包含法律、行政法规、司法解释等9类；不等于2190部现行有效法律。1,777个基本法名last_verified全空；旧民法典仍1062单元，原Markdown缺失。另行取得的官方民法典原件已通过1260条连续分条、DOCX与TXT一致性、逐条位置和哈希机械校验；旧JSON未被覆盖，法律审核未完成。

SQLite当前42版本、人工审核发布0份，其中40份有独立来源元数据；地方累计19份。消防、保险、秸秆三份独立官方HTML不冒称已修复或等同旧附件；秸秆引用卡披露0.8%/08%差异。旧地方固定20样本报告仍16通过、4失败，旧附件问题保留。最新见 docs/mock-and-library-delivery-2026-10-02.md，旧批次见 docs/core-continuation-progress.md；不能与旧镜像合并宣称已核验或全国完整。此前七部法2431条及六部新增基础法1171条为历史批次验收，见 docs/basic-laws-progress.md。此前连接观察（本轮未重测）：吉林/松原首页可读，长春HTTPS仍失败、HTTP栏目只取得外壳；执行/破产首页可读，工商robots521、信用中国412，主体查询仍未接通。

官方原件下载参数已修复（fileType改format），在新进程成功下载民法典；旧分条器遗漏“零/〇”的正则已修复，旧2190项JSON未重建。案例库TLS恢复正常证书验证。四个源码补丁均有备份，当前旧stdio连接需新会话/重连才能加载，详见docs/official-download-diagnosis.md。

工程测试、实际MCP测试与50项模型行为测试分开。2026-10-02工程337项通过，见verification/mock-straw-engineering-2026-10-02.json。加入模拟分支前的核心50项已完整重跑：49通过、B44跨案身份权限部分通过；两批共享上下文，不是50个独立会话，也不是律师验收。见tests/behavior/runs/2026-09-28-current/independent-judgments.json。模拟首版另完成17轮实际演练，辅助审计两处修正后独立复验通过；使用见docs/personal-mock-hearing-guide.md。新增独立条款/案例核验账本区分人工/自动、片段/整法、参照状态/裁判效力，不通过MCP自动审核发布。

## 使用

在新一轮Codex对话中调用：

> 使用持衡检查我的答辩状，先确认我方角色和程序阶段，自动检索依据，分别给出内部审查与拟对外稿。

依用户最新决定，机械校验后直接入库，检索默认返回未人工复核且未撤回资料；实际引用时展示 citation 来源卡、链接、版本、条款/页码和未知字段供审阅。`include_quarantine=false` 仅查询人工审核发布资料，目前为0份。可检索不代表现行有效或法律审核通过。

其他Skill也可调用同一全局连接：`public_corpus_inventory`、`search_public_corpus`、`get_public_corpus_article`。离线先找线索，再使用允许访问的官方来源或用户提供原件核对版本/关键原文。2026-09-28实际观察国家库flk.npc.gov.cn明确禁止自动采集：本项目三个自动入口已阻断，不经其他MCP或换接口绕过；已保存原文可读，现行性仍待核。该阻断不等于替宿主所有第三方工具设置了全局网络封锁。详情目录与截断片段不是完整法规。`menglu-legal-treasury`已加入共享路由；新对话发现更新。

新增 `get_law_article(version_id, article, offset=0, length=5000)`，按已保存原件的中文条号读取（零、〇、条之一）；版本ID由 `search_law` 取得。返回原文 `start/end`、条文哈希、分页状态和原审核状态；重复条号、空正文或无法分条时明确报错。当前共7个只读工具。重跑固定民法典验收：`.venv/bin/python scripts/verify_civil_code_articles.py`，随后运行 `scripts/smoke_shared_library.py`。

三个验收版本使用同一输出结构和深度，文末提示不同。事实、来源或时效不足仍就近说明。

## ChatGPT与插件

插件ZIP包含Skill与本机MCP连接配置；尚未在ChatGPT账号中安装和端到端验证。云端ChatGPT不能仅靠127.0.0.1连入。官方私有Secure MCP Tunnel可用于后续接入，但需真实隧道ID、运行密钥、工作区关联及权限。详见docs/chatgpt-private-connection.md；没有开放公网或上传案件资料。

## 已知限制与后续

- 全国法规、31省级地方来源、地方规范全文持续入库尚未完成。
- 工商、执行、信用中国、破产入口已实测，实际主体/案件查询连接未完成；当前仅显式人工触发诊断，不自动查询。
- 企查查/天眼查使用网页会员人工查询和官方导出。正式商业API/MCP尚未获供应商授权。
- 自动检查不等于人工法律审核，不会在月报时自动升级效力/引用状态。全国目录差集仅用于发现候选，不能当作新增全文。
- 31省级地方规范正文覆盖分母尚未建立；月报明确逐省缺口，不能宣称完整或绝无遗漏。
- 当前文书模板是方法工具；真实案件依承办律师复核签发。

## 检查与恢复

项目：`/Users/songmenglvshi/Documents/Codex/2026-09-23/xia/work/cn-legal-review`

查看服务：`launchctl print gui/501/com.chiheng.legal-mcp`

重启服务：`launchctl kickstart -k gui/501/com.chiheng.legal-mcp`

日志在项目 `verification/`。SQLite 数据在 `data/legal.sqlite3`，原始快照在 `data/quarantine/`。

备份数据库应使用SQLite backup接口或停止服务后备份数据库及WAL文件；不要在运行中只复制主数据库并声称完整备份。

暂停后台服务：`launchctl bootout gui/501/com.chiheng.legal-mcp`。统一更新任务：`launchctl bootout gui/501/com.menglu.legal-update`。此操作保留全部文件，重新bootstrap对应LaunchAgents文件即可恢复。

旧3个定时任务已卸载并将plist移至verification/launchd-backup，可恢复；避免新旧任务在登录后重复启动。请勿同时恢复旧任务和统一调度。

移除Codex连接：`codex mcp remove chiheng-legal`。仅移除配置，不删除资料。Skill和Plugin压缩包均不包含会员凭据、客户材料、数据库或Python环境。
