# Windows 10 原生迁移实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前公开法库、持衡插件与模拟法庭交付为可核验的 Windows 10 原生迁移包，准确区分工程验证和目标机验收。

**Architecture:** 复用现有 SQLite 迁移与检索服务；平台差异集中在锁、路径、文件保护和安装入口。保留 Mac 行为，Windows 环境本地重建；新任务不修改原数据库、不启用本机后台服务。

**Tech Stack:** Python标准库、现有MCP/SQLite/公开库迁移接口、Windows原生任务计划；第三方依赖与浏览器兼容性独立检查。

工作根目录：`/Users/songmenglvshi/Documents/Codex/2026-09-23/xia/work/cn-legal-review`。当前非Git目录，不创建仓库或提交；变更前保留限定源码快照和哈希。使用本目录 `.venv/bin/python -B` 运行本机验证。下列代码展示接口与可运行的验收入口；Windows系统调用必须依据官方文档和红绿测试实现，不能将模拟调用标成实机证据。

## Task 0：记录基线和兼容依赖

- [x] 保存将修改的程序/测试原件至 `verification/windows10-2026-10-09/before/`，记录哈希。只复制白名单源码，不复制凭据、数据库或案卷。
- [x] 离线重跑完整测试，确认532项旧基线；网络被阻止，既有测试中的模拟请求不算真实联网。

```sh
.venv/bin/python -B -m unittest discover -s tests -q
```

- [x] 核对 `requirements*.txt`、Scrapling/Playwright/Patchright、bb-browser/Node、国家库和案例库客户端、LibreOffice与Codex安装入口。保存版本、来源、包含方式和Windows 10支持状态。不要把Windows 11官方支持范围当成Windows 10通过证据。

## Task 1：跨平台资料锁与迁移恢复

文件：新增 `portable_lock.py`、`tests/test_windows_portability.py`；修改所有使用 `fcntl` 的项目入口及 `library_transfer.py`。`mock_hearing.py` 本任务仅切换锁导入，不移除权限保护；Windows私有文件保护在Task 2处理。

- [x] 先写失败测试：没有fcntl时仍能导入；同文件跨进程排他竞争；共享/排他兼容；退出释放；不改变流位置和正文；拒绝Windows危险文件名。

```python
for name in ('data/quarantine/CON.txt', 'data/quarantine/a.','data/quarantine/a ',
             'data/quarantine/NUL', 'data/quarantine/x?y'):
    with self.assertRaises(ValueError):
        library_transfer._safe_name(name)
```

- [x] 运行新增测试确认对应缺口真实失败，留存红灯输出。
- [x] 提供 `flock(file_or_fd, operation)` 和 `LOCK_SH/LOCK_EX/LOCK_NB/LOCK_UN` 的小型适配。POSIX保持原flock；Windows锁使用受控区域及实际句柄，不把正文范围锁坏，不把拒绝访问混同忙锁。所有调用共同使用一个入口，不增加第二种并发协议。
- [x] Windows目录发布使用禁止覆盖操作，并在解包前验证保留名称、尾点空格、大小写/Unicode冲突、重解析点与路径穿越；目标出现竞态时不得覆盖。

```python
if sys.platform == 'win32':
    os.rename(source, target)  # Windows拒绝已有目标；绝不改为replace。
    return
```

- [x] 跑目标测试与完整回归，独立规格审查后再质量审查；Windows锁实测单列待验。

## Task 2：模拟法庭私有文件 Windows 保护

文件：`mock_hearing.py`、必要的小型 `windows_private.py`、`tests/test_windows_private.py`。

- [x] 先测试Windows不支持Unix权限位及O_NOFOLLOW时的行为；保留POSIX原测试，不能删断言换取通过。
- [x] 为Windows建立独立私有演练目录保护：只对新建目录设置当前用户/SYSTEM/管理员的有限ACL，已有目录仅检查，宽权限拒绝而非擅自修改。拒绝重解析点和多硬链接，通过句柄核验已打开文件，避免只靠路径预检。
- [x] Windows不能安全完成ACL/句柄检查时明确失败，不降级为仅检查文件存在。测试用合成案卷，不能接触真实会话。
- [x] 现有stage、引用卡、审计、复练行为保持不变。完成本机合成演练检查，规格/质量独立审查；Windows整轮演练测试已提供但实机待验。

## Task 3：Windows安装与自启动

文件：新增 `scripts/install_windows.py`、`scripts/windows_tasks.ps1`、`tests/test_windows_install.py`；必要修改 `local_settings.py`；新增Windows依赖清单。仅提取现有安装器确实共享的检查，不做无关重构。

本任务分为3A核心安装与计划任务、3B外部法律连接与专用浏览器入口，逐批实现、复核，避免同时修改安装器。运行环境采用已核对的官方 Python 3.13.16 x64 ZIP，在最终安装目录建立虚拟环境；已备齐带哈希的主环境79个wheel及外部MCP 1环境31个wheel。浏览器维护边界与Windows原生验收不变。

- [x] 写失败测试覆盖非Windows/错误架构、缺Python、目标已存在、依赖失败、校验失败、端口冲突、任务同名和停用不删除资料。另补再启用、写入中断和回滚；原生执行另列Task 5。
- [x] 安装核心流程：检查目标机，`restore_library(archive, target)`，复制明确允许源码，最终目录创建venv，按Windows清单安装依赖，用真实保存条目检查中文检索、来源卡、原文和镜像回读。工程检查完成，Windows运行未验。

```python
runtime_python = target / '.venv' / 'Scripts' / 'python.exe'
subprocess.run([str(selected), '-X', 'utf8', '-m', 'venv', str(target / '.venv')],
               check=True, timeout=180)
```

- [x] 外部受控命令使用参数数组、有限超时；UTF-8及上海时区有显式探针，中文/空格路径进入合成测试。运行时来源与身份已核对，未使用Mac依赖作为Windows运行证明。未迁移的浏览器旁路/更新/历史路线明确拒绝，原生实际运行仍列Task 5。
- [x] 启动入口仅本机；当前用户计划任务登录启动并定期调用现有调度。检查后按用户选项启用；禁用SYSTEM、最高权限及密码保存。已有任务不覆盖；仅本安装两项均停用且身份一致时可恢复启用，失败区分新建/恢复回滚。Windows任务计划实机待验。
- [x] 生成Codex连接片段并提供目标已有连接名称检查，不写宿主配置；Skill只复制到新安装目录，宿主导入与冲突核对由目标机本人完成。可选Obsidian仅用指定vault写托管笔记；Task 4补总迁移说明，实际宿主验收仍列Task 5。
- [x] 核心doctor分项输出检索/模拟法庭/PDF/更新/浏览器/自启动状态；未验证字段不得默认为true。Task 3B继续接入外部组件的独立检测。

## Task 4：完整总包与恢复验证

文件：新增 `scripts/build_windows_delivery.py`、`tests/test_windows_delivery.py`、`docs/windows10-migration-guide.md`。

- [ ] 先测试包内白名单、秘密/会话排除、源文件变更检测及清单校验失败；总包包含程序、两类Skill、插件、公开资料、所需外部客户端、必要测试资产及本项目Obsidian小笔记，保留许可。
- [ ] 复用导出接口，不调用会覆盖旧ZIP的旧main：

```python
from library_transfer import export_library, verify_archive
manifest = export_library(root, output / 'personal-public-library.zip')
assert verify_archive(output / 'personal-public-library.zip') == manifest
```

- [ ] 清单记录每文件SHA-256、版本、原件来源与许可；单一外层ZIP放入全新输出目录。当前无法合法/安全带入的外部组件列出获取方法与功能影响，不宣称全离线或全部可用。
- [ ] 干净目录解压和恢复，核对数据库全部核心表、文件哈希、引用及离线镜像。重跑包内可运行测试，确保不会依赖源Mac绝对路径。
- [ ] 主代理复核、规格和质量审查；更新项目记忆与状态报告，交付可点击总包、说明和校验值。

## Task 5：Windows 10目标机验收

- [ ] 记录系统版本/构建号/架构，安装、实际MCP调用、合成庭审、公开网页、登录检索和重登录自启动分别验收。
- [ ] 未取得目标机执行连接前，本项保持未完成，不自动部署到其他主机、不上传公开仓库做测试。浏览器若无可维护兼容方案，先报告影响并征求功能替代授权。

## 进度记录

2026-10-09：设计已获用户确认；本计划进入Task 0。不再要求用户重复批准同一设计。采用子代理逐任务实施和两阶段复核，不并行修改重叠代码；主代理处理来源核对、整合与最终交付。

2026-10-09：Task 0、Task 1工程验证完成。旧基线532项通过；Task 1完整回归541项通过、1项Windows原生测试跳过，两阶段审查通过，详见 `verification/windows10-2026-10-09/`。Task 2进行中。Windows依赖解析报告只证明分发文件可解析，不证明Windows运行成功；外部MCP 1客户端须与主MCP 2环境隔离。Task 5仍未开始。

2026-10-09：Task 2工程复核通过。质量审查发现祖先目录零访问权限不能阻止改名，已改为参与共享检查的FILE_LIST_DIRECTORY并补测试；首轮失败与复核证据均保留。主代理独立离线全量回归556项：547通过、9项Windows原生跳过，18.436秒，工具记录794a69/d20bff。进入Task 3A。下载与依赖证据见 `runtime-sources.md`；主库、真实凭据和本机服务未修改。

2026-10-09：Task 3A安装器已实现。规格审查要求在目标机明确展示自启动选择，已补交互及显式启用/跳过开关，规格复核通过；质量审查进行中。主代理对本修订独立离线运行579项：570通过、9原生待验，18.988秒，工具记录df859e/48382d。日志网页响应来自夹具，并非联网抓取。Task 3B和总包仍未完成。

2026-10-11：恢复中断的质量审查，修复停用后无法再次启用、状态文件中途写坏导致回滚身份丢失两项P2，最终质量复核PASS。主代理独立离线585项：575通过、10项原生/PowerShell跳过，19.021秒，工具记录3c2afe/acc55a/5299bf；定向39项37通过2跳过。Task 3A工程完成，Task 3B外部连接与浏览器实施中，尚无最终Windows总ZIP。原Mac安装、主库、账号凭据与系统设置未改动。

2026-10-11后续：Task 3B两阶段最终PASS。修复OpenClaw/日常历史旁路、CLI超时、站点隐式更新与旧目录，以及并发失败误删daemon状态；Windows保留状态人工复核，不自动杀进程或清理旧profile。主代理最终离线610项：598通过、12原生待验，18.851秒（e92362/5ca504）；真实副本JS合成12项通过（b42787）。SDK1与SDK2隔离，案例认证只走新安装私有目录、真实三步待用户重新登录，国家库封锁保留。Task 4总包与Skill Windows副本开始实施；ZIP尚未交付，Task 5未执行。
