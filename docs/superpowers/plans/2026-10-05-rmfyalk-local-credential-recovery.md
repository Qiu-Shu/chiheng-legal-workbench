# 人民法院案例库凭证恢复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 原本机凭证更新后无须反复重启，失效明确提示重新登录，并以认证、案例检索、详情回读三步验证实际网站可用。

**Architecture:** 改造既有客户端，在每次请求前安全读取同一文件，按实际凭证值隔离失效状态，每个请求持有自己的认证快照。原服务工具统一使用此路径；认证检查增加限量三步验证，不增服务、依赖或采集授权。

**Tech Stack:** 已有 Python、unittest、httpx、python-dotenv、FastMCP；无新增依赖。

## 路径和职责

- 改：`/Users/songmenglvshi/Documents/Codex/2026-06-25/wo-s/work/menglu-legal-treasury/sources/legal-tools/人民法院案例库MCP/scripts/client.py`，负责安全读文件、请求快照、错误分类与失效阻断。
- 改：同目录 `server.py`，负责中文提示、三步可用验证、枚举归一、统计及导出认证中断。
- 新：本项目 `tests/test_rmfyalk_recovery.py`、`tests/test_rmfyalk_recovery_server.py`，独立于真实凭证测试客户端与工具行为。
- 新：本项目 `docs/rmfyalk-credential-recovery-guide.md` 和 `verification/rmfyalk-recovery-2026-10-05/`，存无秘密的操作说明、原源码备份、测试与复核记录。
- 改：已有验收报告及三份 Obsidian 托管笔记，只记录状态；修正法律宝典配置引用中与本流程相关的文件路径。

工作区及上游源码均非 Git 仓库，不创建 worktree、不伪称提交。只备份两份源码，不复制 `.env` 或整个上游目录。实现代理独占两份源码和两份新测试，其他代理只读复核。

## 任务1 改造客户端并统一工具

- [x] 留存两份非秘密原源码，先写测试。测试使用临时 `.env`、虚构凭证、httpx 模拟传输；隔离导入时的 dotenv，不读实际文件、不联网、不导出真实资料。
- [x] 运行新测试，确认因旧值缓存、错误提示或仅认证未验证详情等缺失而失败，保存完整退出码和结果；不得仅以导入错误代替失败证明。

运行：

```sh
.venv/bin/python -B -m unittest discover -s tests -p 'test_rmfyalk_recovery*.py' -v
```

最低行为断言包括：

```python
# 同进程A被拒绝后，保存B，下一次请求恢复；失败不重试。
await client.post("cpwsAl/search", {"page": 1, "size": 1})
# 用临时文件的新值B再次调用，断言实际请求认证头为B。
# 对同一失效A重复调用，断言网站请求计数不增加。
```

- [x] 实现 `RmfyalkClient(credential_path=None)`：缺省定位源目录上一级 `.env`，显式路径供同一读取器用于临时测试。读取普通文件，打开时拒绝软链接并用文件描述符验证所有者/权限/类型，上限64KiB。用现有 dotenv 解析器禁用插值，拒绝损坏绑定、重复目标键、控制字符和空值，不输出解析行。只读目标键，不将其注入进程环境。
- [x] 保留既有 `EXPORT_DIR` 启动用途但不加载认证到全局环境。普通请求忽略遗留认证环境值；文件有问题时暂停，不能回退旧缓存。每次调用读取而非只检查mtime或长度。
- [x] 凭证代次只按有效键值变化。数字 `exp` 可用于提前阻断，未知字段交由官网判断；失效代次在内存阻断，旧代次的迟到401不得污染新值。每个请求传递自己的 `headers={"faxin-cpws-al-token": token}`，不修改共享默认头，不关闭正在使用的共享客户端。
- [x] HTTP401与业务401均归认证失败；缺失/空白/安全错误归文件状态；403/500/超时/TLS/JSON异常归对应固定安全错误，不原样回显底层错误、响应或身份。无自动重试。保留检索体构造不变。
- [x] 客户端提供 `CredentialError`、`TokenExpiredError` 和 `ApiError` 三种安全错误，服务统一处理；`client.token` 在正常流程中触发安全读取，不能暴露启动旧值。兼容原set工具使用 `verify_token(token)` 临时请求，不覆盖正常文件认证源、不持久化。
- [x] 服务 `_handle_error` 对文件和认证状态给固定中文说明；认证失效写明“需要您重新登录官网”，链接官网，提示仅在本机保存，不要求chat/set工具传秘密。其他未知异常仅输出类型安全类别。
- [x] 枚举改用 `client.get("common/getXmlToTree?...编码参数...")`，保留原参数/返回结构并启用TLS验证。统计内部可选请求、导出翻页/详情遇到认证或文件错误立即停止，不吞错，不宣称部分数据全部成功；已写入部分只如实报告数量。
- [x] `check_token()` 限量完成下列顺序，只有全部通过才输出“网站实际可用”，否则逐步说明未完成，不返回用户身份、负载或凭证。

```python
token_before = client.token
auth = await client.post("user/getUserInfo", {"state": ""}, expected_token=token_before)
# 每一步实际捕获值必须等于起始值；阶段结束也检查变化。
body = client.build_search_body(keyword="买卖合同", page=1, page_size=1)
hits = await client.post("cpwsAl/search", body, expected_token=token_before)
# auth非空data对象、hits.data.datas首条非空case_id均需检查。
# 取真实命中的cpws_al_id；detail.data.data须有非空案例正文。
# 检索和详情存在的稳定编号/案号不能互相矛盾；编码ID不要求相同。
# token_before与最终client.token不相同，不称本次完整验证成功。
```

- [x] 三步测试覆盖认证失败、认证通过但查询失败/零命中、详情失败/空白/不匹配、期间凭证变化、三步成功，以及错误载荷含虚构秘密仍不泄露。仅返回安全阶段说明，不把网页会员/认证成功当成开放API授权。
- [x] 重跑新测试及原 `test_vendor_download.py`；客户端、工具和一条正常查询链在同一模拟进程集成，发现遗漏先加失败测试再修复。自检只报告工程结果，不访问真实网站。

## 任务2 规格及代码质量复核

- [x] 独立规格代理逐项读真实源码及测试，核对已批准设计和用户新增要求；不相信实现报告、不读真实凭证。发现遗漏由实现代理修复并重新验收。
- [x] 规格复核通过后另派质量代理，检查读取竞态、代次并发、工具输出隐私、错误分类、兼容接口与测试隔离，执行自己的虚构探针；未通过不得进入部署验收。
- [x] 主代理重新运行专项与全量工程测试，检查退出码与警告，将模拟网页日志明确标为测试，不称真实抓取。

```sh
.venv/bin/python -B -m unittest discover -s tests -p 'test_rmfyalk_recovery*.py' -v
.venv/bin/python -B -m unittest discover -s tests -v
```

## 任务3 部署说明和真实验收

- [x] 保存用户操作说明：什么时候需重新登录、原本机文件位置、首次加载需重建连接、以后文件更新后调用检查即可。明确查询时提示而不是后台弹窗，不上传秘密。
- [x] 核对当前正式工具是否已加载改造：2026-10-05用户正常重开后，当前注册工具说明和实际返回均体现新版。没有杀进程或代执行重开，旧输出不算部署成功。
- [x] 用户本人更新有效凭证后，通过当前正式工具调用三步检查：2026-10-05重开后主代理只调用一次，真实认证、单条检索和对应正文全部通过；不是本地布尔检查、网页登录报告、工程模拟或临时连接替代。此前失败记录保留。
- [x] 更新验收报告和记忆：分别记录工程通过、代码是否加载、真实网站是否三步通过，剩余案例网页定位/原裁判/入库/云端缺口不变。无新秘密文件、无移植包或全国覆盖变更。

## 计划自检

设计中读取、安全、失效、并发、旧接口、枚举和中断要求对应任务1；独立审查对应任务2；用户提示、实际可用与部署边界对应任务3。接口名和路径一致；没有添加服务、登录绕过或新的抓取任务。用户已授权实施，不再为执行方式重复确认，采用单实现代理与顺序独立审查。
