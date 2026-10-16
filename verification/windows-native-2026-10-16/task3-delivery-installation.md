# Task 3 — 新候选与 Windows 隔离安装验收

2026-10-16。固定源提交：`ccadffa3d7526cc57369d6c3a633d40c54bb08e8`。本次复用既有构建器、公开库迁移器和 Windows 安装器，没有新增产品代码。结果是核心安装和离线工程验收通过，不是全部 Task 5 在线功能完成。

## 最终候选

- 目录：`D:/Documents/群兴桌面验证/持衡候选/chiheng-windows10-2026-10-16-phta_8wh`。
- ZIP：`持衡-Windows10-x64-个人迁移总包.zip`，**255563418 字节**。
- SHA-256：`7ef614242853903f6130516eafcdd6c53defaf69d03658de56a39db7b3703b88`。
- 外层 **455 个载荷加 manifest，共456个成员**；全量摘要及 ZIP CRC 通过。
- 192 个当前源码文件以及共338个源码、Skill、插件、vendor和交付说明文件与工作副本逐摘要一致。构建器还检查全部来源在复制前后及发布前不变。
- 内层 **590 个公开库载荷**全部核验；原包的检查点、配置和来源说明完整保留，除 SQLite 备份的物理字节外，全部公开载荷与原归档摘要一致。数据库逻辑内容、镜像和台账一致。

同目录保留 `SHA256.txt`、`内容清单.json`、`先读我-迁移说明.md` 和新的 `已核验解压`。精确路径与计数见 `task3-candidate-verified.json`。候选使用上述固定提交；本报告和计划的验收状态更新是在打包后新增，未更改已经验收的产品源码。

## 构建输入与首候选保留

原恢复包重新核验452个载荷。复制其已核验运行时至独立构建输入，保留 Python 3.13.16、Node 22.23.3、pnpm 11.25.0 原始摘要及来源说明，79个主环境wheel、31个SDK1 wheel和1个ReportLab wheel。原运行时 ZIP 中的许可文件、wheel 元数据与既有组件来源说明保留。

第一次候选位于 `chiheng-windows10-2026-10-16-yh4o934j`，SHA-256 为 `1a353fa5ca7d03d3a6a5529d08d4b303f5a4906de2921f3291b250f9457a3e2f`，255562632字节。构建命令退出0，但独立验收未采用它：开发副本只导出589个公开载荷，缺少原 `verification/scheduler-state.json`，六个配置及一个来源说明与原包仅有CRLF字节差异。没有把这一候选安装或当作最终交付。

随后用 `restore_library` 将原590个载荷恢复到新的构建暂存根，再独占复制当前选中的源码和vendor，调用同一 `build_windows_delivery.build` 重建。首候选与全部原始构建清单保留；三份完整清单放在忽略目录 `.local/task3-raw-evidence-20261016`，摘要与拒绝原因纳入 `task3-delivery-summary.json`，没有重复把公共库全量清单加入Git。

## 新安装与实测

新安装目录为 **`D:/Documents/群兴桌面验证/持衡运行 02`**。首次失败的“持衡运行 01”、原下载归档和原公共库均未覆盖。本次仅公开资料及明确标记的合成演练，没有迁移真实私案、认证值或用户机器配置。

安装调用已核验候选内的 `scripts.install_windows.install`，40.943秒、退出0，状态 `complete`、`activated=false`。只将宿主配置名字检查替换为明确的 `not_checked_scope_no_host_config_read`；其余安装、离线pip、doctor、原生检查和组件安装执行现有实现。没有调用激活入口、注册计划任务或导入全局MCP。

| 实测项 | 实际结果 | 退出码/证据 |
| --- | --- | --- |
| 安装内完整入口 `.venv/Scripts/python.exe -E -s -X utf8 -B scripts/test_windows_offline.py` | **632项，625通过、7明确跳过，79.415秒** | 0；`task3-installed-full-offline.log` |
| 包内真实vendor函数JS边界 | **12/12通过** | 0；`task3-installed-js-boundary.log` |
| 安装及后续新进程doctor | 搜索、PDF、合成演练ready；错误列表空；每次真实原生安全 **8/8通过、0skip** | 0；`task3-install-result.json`、`task3-installed-doctor-restart.log` |
| 两个独立Python环境 | 均为3.13.16、自身安装内runtime；主锁 **79/79** 版本及位置匹配，MCP **2.2.0**；SDK1锁 **31/31**匹配，MCP **1.28.0** | 两次0；环境日志及summary |
| 依赖一致性 | 两环境 `pip check` 均为 `No broken requirements found` | 两次0；终端记录 |
| 全公开库及来源卡 | 590载荷摘要、全部核心表逻辑摘要；**49检索、49原文片段、49来源卡**逐一核对 | 0；`task3-installed-data.log` |
| 安装文件身份 | 338个已复制载荷、3159个Python运行时文件逐字节摘要一致；原公开归档及候选摘要不变 | 0；`task3-installed-file-identity.json` |
| 合成演练退出后保留 | 三个独立进程：创建1回合→恢复并完成11回合→重新打开11回合；后两次会话摘要一致 | 三次0；create/resume/reopen日志 |

最终合成会话摘要：`21f000d2a45e5b4181d858350a9b03c73b7405567b44f8af9c694243d39efd23`，保留于新安装的 `private/acceptance-synthetic`。只表示结构演练完成，`human_review`仍为空，不代表律师批准或真实裁判。

验证器 `task3-installed-acceptance.py` 在新安装目录及其解释器运行；数据、环境和演练检查的当前进程通过审计钩子拒绝旧源码、旧01安装和宿主配置读取。钩子不宣称覆盖全部子进程。环境扫描器初次只计78项，原因是漏匹配 `scrapling[fetchers]`；原日志保留，加入extras解析及总行数断言后重跑79项全部匹配。产品和锁文件未因此修改。

公开库仍为49版本、49来源、49全文索引、100审计；逻辑摘要 `82b6a97660190154d5ac72df38e2b2bd817c40f2aa6705e3ea9bb8b74765c3be`。镜像2190版本、77809文本单元，保留 `unverified_mirror`、`coverage_complete=false`及引用时审阅要求。原公开ZIP摘要仍为 `50bb70dd01b6432b6fdc946fcf17c8afb075cbf26258edbc6ed460b02c38e791`。

## 明确边界与提交范围

7项skip与此前相同：2项POSIX mode、2项POSIX凭据flags/FIFO/owner、1项POSIX flock、1项macOS转换器、1项未安装LibreOffice的真实DOC转换。原生Windows安全和合成演练未跳过。离线入口保护当前测试进程常用TCP、asyncio和Fetcher入口，不是系统级联网沙盒。

浏览器依赖按既有冻结锁、完整性校验及禁用生命周期脚本恢复；Node/pnpm/bb-browser版本导入通过，实际安装的14个包均有许可标签（MIT、Apache-2.0、BSD-3-Clause及组合）。这只是既有锁定包元数据核对，不是完整法律许可审计。没有启动实际浏览器会话或网站；`installed_native_pending`与在线能力未验状态保留。

未运行：真实DOC转换、业务网站登录及认证→检索→正文、宿主MCP导入/HTTP服务、计划任务、Windows注销/重启。三进程保留验证不能替代操作系统重新登录验收。国家库保持 `FLK_ACCESS_BLOCK`，不宣称整个应用支持任意深安装路径。

用户本轮明确要求上传GitHub，覆盖此前“只在本机提交”的历史限制。父代理已将截至 `ccadffa` 的前三个提交上传既有私有仓库 `codex/windows-native-continuation` 分支并核对406文件一致；本阶段验收证据经父代理与独立审阅复核，由本次文档提交保存并续推。最终远端SHA及递归树比对回执保存在群兴主项目的 `.audit-local/github-upload-20261016`。运行锁、ZIP、环境、公开库及合成私有会话不纳入本次代码提交。
