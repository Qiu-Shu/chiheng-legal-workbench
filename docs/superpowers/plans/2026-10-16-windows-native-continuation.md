# Windows 原生续建与材料接口前置验证

> 使用已批准无人值守范围，执行方式为 implement + inline 执行；code-review 双轴独立复核。复用已有 Task4/5，不重做 Task0—3B。

**Goal:** 使既有持衡引擎在当前 Windows 10 x64 真正通过隔离安装、权限/锁和合成演练验证，为群兴统一材料接口提供可运行基础。

**Architecture:** 保持独立 Python 3.13.16 主环境和 MCP1 环境，复用现有安装/资料恢复/权限/演练模块。仅修复实测缺陷和不便携测试夹具，不把宿主连接、网站登录或人工法律复核当作安装成功。

**Tech Stack:** 现有 Python、pywin32 312、SQLite/MCP、锁定 Windows wheel 与 Node/pnpm，核心无需另加依赖。

**Spec:** docs/superpowers/plans/2026-10-09-windows10-migration.md Task4/5、verification/windows10-2026-10-11/task4-spec-review.md、HANDOFF.md；用户当前群兴 Windows 整合及无人值守授权优先，旧 Mac 路径与“不提交”只描述其当时环境。

## 约束与复核重点

- 基线 e09e47fa4a93763cb50c0b8df3004bb10200cde1，当前分支 codex/windows-native-continuation。只在本机提交。
- 原下载归档、首次失败安装目录与日志保留。新候选与新安装目录分别创建，禁止覆盖真实数据或启用自动服务。
- 私案不入共享法库；演练只用合成材料。公开资料恢复保留原版本、来源及 unverified/quarantine 状态。
- ACL/重解析点/硬链接/并发检查不能因 Windows 失败而跳过；只有真实平台专属断言或确定缺失的系统能力明确分流。
- 入口、锁、未授权访问、文件首建失败及路径别名必须实测；只看模拟 API 测试不算原生通过。
- 最终候选须逐文件与实际修改源码核对，Windows 和 Mac 历史结果分别报告。

## Task 1 — 原生接口缺陷

涉及 windows_private.py、tests/test_windows_private.py，以及对应调用者。

- [x] 用旧恢复包首次本机隔离安装；状态失败，法库/PDF ready，8项原生私有文件测试因 win32con 缺少 FILE_FLAG_OPEN_REPARSE_POINT 报错。证据在父目录 chiheng-install-01.log 和独立安装 verification/install/state.json。
- [x] 从当前源码复现最小原生失败，核对依赖版本、模块常量和文件身份。旧源码8项原生错误均为同一缺失常量，见父目录 native-source-red.log。
- [x] 最小修复错误接口，保留无删除共享、禁止跟随重解析点及句柄验证。tests.test_windows_private 14项通过（其中8项真实原生，含合成完整演练），退出0；锁/传输另10项通过，1项POSIX专属跳过，退出0。见父目录 native-source-after-constant.log、windows-portability-first.log。独立复核另记。

## Task 2 — Windows 夹具与完整离线回归

涉及 tests/test_mac_install.py、test_mock_hearing.py、test_hearing_rehearsal.py、test_local_settings.py、test_library_transfer.py、test_windows_portability.py 和实际关联测试。

- [x] 复用隔离运行时，在源码目录恢复开发用公共资料副本和测试依赖；主MCP2与SDK1分开，49版本/100审计、2190镜像/77809单元不变。深路径恢复失败后通过短临时路径恢复；深路径限制另留后续。
- [x] 保留118项初始RED及37项关联RED，修正实际API故障注入、私有ACL夹具、链接能力判断及实测路径/字节/连接拦截假设，保留法律/演练业务断言。
- [x] Standards指出Proactor绕过后补2项RED并在异步连接入口修复，完整offline 629项622通过7明确skip，退出0；JS前次12/12通过，退出0。仅测试进程常用TCP/asyncio/Fetcher入口受保护，非系统级联网沙盒。详 `verification/windows-native-2026-10-16/task2-portable-fixtures.md`，其余独立复核与新交付仍在Task3。

## Task 3 — 新候选、独审与本机交付

- [ ] code-review 从固定基线独立双轴审查，修复与复验实证问题。
- [ ] 复用 build_windows_delivery 生成新的源码一致候选；全部载荷/公开原文/来源卡/核心表校验，安装到新中文空格目录。
- [ ] 新安装主/SDK1环境、原生安全与合成演练、公开检索/正文/PDF逐项实测。宿主网站登录/计划任务等未执行项单列，不冒称 Task5 全部完成。
- [ ] 保存证据、提交本地分支，更新群兴主项目状态和 Obsidian。之后继续统一材料接口及既定程序任务。
