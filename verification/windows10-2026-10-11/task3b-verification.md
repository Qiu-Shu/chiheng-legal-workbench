# Task 3B 外部组件实现交接

2026-10-11。状态：DONE_WITH_CONCERNS。迁移源码、安装接口和本机合成检查已完成；没有 Windows 连接，未执行 Windows 二进制、ACL、PowerShell/CIM、真实账号或真实浏览器验收。

同日独立规格审查发现四项浏览器缺口，现已修复并提交复核。最新全量为 610 项、598 通过、12 原生待验；新版补丁身份、四项修复和下文“案例48项”的定向夹具限制见 [审查修复记录](task3b-review-fixes.md)。下文早期数值保留为历史，不能代替最新结果或独立复核结论。

## 改动范围

已有主项目文件仅改 `scripts/install_windows.py`：复用 ZIP 解包函数时允许指定必需入口；核心 doctor 增加独立外部诊断；核心检查通过后安装外部组件，并把 `completion_scope` 记为 `core_only_external_status_separate`。原件和原哈希分别在 `task3b-before/install_windows.py`、`task3b-before.sha256`。

新增 `windows_external.py`、`windows_case_access.py`、`windows_browser.py`、`scripts/windows_flk_blocked.py`、`tests/test_windows_external.py`、`tests/windows_bb_boundary.mjs`、`docs/windows-external-setup.md`。

vendor 共 52 文件。两法库只按盘点白名单复制当前六个脚本、requirements、README、API 参考和总许可；只有案例 client 副本发生修改。bb 包含根 package/冻结锁、实际 npm 包的白名单 dist/web/shared/README/LICENSE、已有边界补丁溯源。补充两份来源说明、输入哈希清单以及白名单 daemon.js 的补丁前副本供合成安装测试。没有复制 `.env`、`.python-deps`、Mac node_modules、Cookie、浏览器 profile 或日志目录。

原 Treasury 案例 client 和原 bb CLI/daemon 的最终哈希与复制前一致，见 `task3b-originals-unchanged.sha256`。没有改原程序、已安装 Skill、生产数据库、法律规则、国家库禁令、镜像状态或法源审阅状态；未 init/commit Git。新源码中的 private 路径只在目标机使用，未建立本项目真实凭据。

## 接口和行为

`windows_external.install_components(bundle, target)` 接收已由核心清单检查、复制后的最终 target。使用 `runtime/python/python.exe` 创建 `.venv-mcp1`，从 `bundle/runtime/wheels-mcp1` 配合目标根锁文件执行 `--no-index --require-hashes`。探针真正导入 `mcp.server.fastmcp.FastMCP` 且核对 MCP 1.28.0，不使用 find_spec 判定成功，不改变主 SDK2 venv。

Node 解到 `runtime/node/node-v22.23.3-win-x64/node.exe`，pnpm 解到 `runtime/pnpm/package/bin/pnpm.cjs`。二者 archive hash 与 Task3A 下载记录一致。Node/pnpm 版本检查、冻结 pnpm 依赖重建、补丁来源核对和 CLI version 分开处理；网络依赖获取明确不是全离线。新依赖目录中上游 CLI/daemon 身份匹配后才覆盖副本补丁。每次受控调用复核补丁 SHA-256。

`windows_external.doctor(target)` 独立报告 mcp1、case、bb_browser、host、flk 状态。组件失败记录安全的阶段和异常类别，不保存原始 stderr 或认证值。外部 `ready_external` 维持 false；国家库 blocked、案例待本人登录三步检查、浏览器全命令待验。核心安装 complete 不抬升这些状态。

`windows_case_access.access_path()` 唯一返回当前安装 `private/case-access.env`。复制 client 在定义默认值时调用它，因此 `_startup_export_dir`、全局 client 及后续 token 重读从一开始都使用该路径。Windows 安全打开复用 `windows_private.open_file(private=True)`；有界读取、token 格式/过期、换证重读、错误分类、TLS 和 server 三步流程保留。隐藏输入保存使用私有 ACL、新临时文件、原子替换；失败保留旧内容。无环境 token 回退，无网页 Cookie 自动提取。

外部 TOML 生成到 `verification/install/codex-external-mcp.toml`，名称为 `menglu_rmfyalk`、`menglu_flk_npc`，指向最终 SDK1 Python；案例调用根 `windows_case_access.py`，国家库调用 `scripts/windows_flk_blocked.py`。后者只报告原 `FLK_ACCESS_BLOCK`，退出码 2，不导入 vendor 国家库客户端或自动联网。宿主名称检查只返回冲突名称，不拷贝/修改宿主配置；非 Windows 本机不访问 Mac Codex 配置。

浏览器 wrapper 仅使用 `127.0.0.1:19224`，清 hub/PINIX 和 Node 注入环境。新浏览器通过用户指定或 Windows 常规路径定位，再核对 Authenticode 产品签名与官方当前稳定版本元数据；无法核对报告 pending。独立 profile 与状态目录私有 ACL，端口 19224 和新 daemon 的 19824 占用均拒绝。CIM 核对 PID、创建时间、可执行路径、命令和监听归属。只有单独 help/version 豁免连接检查；CDP 失联不转向其他端口。Windows 副本 daemon 启动带 `--no-chrome`，不自动下载 Chrome；未知/陈旧状态拒绝，不清理、不杀 PID。raw daemon 控制及 Unix history 路线拒绝。

浏览器关闭、重启或遗留状态后的人工身份复核是本轮明确保留的操作限制。没有扩展成自动恢复进程管理器，也不删除旧 profile。现有源码保留不代表全部命令兼容 Windows 10。

## 验证证据

- `task3b-red.log`：最初 11 项针对不存在适配器的预期失败。
- `task3b-native-error-red.log`：Windows 原生错误类别未转换的红测试，随后修复为安全分类。
- `task3b-daemon-port-red.log`：daemon 端口已占用仍继续的红测试，随后加入拒绝。
- `task3b-diagnostic-red.log`：外部诊断和安全阶段报告缺失的红测试。
- `task3b-final-external.log`：22 项中 20 通过、2 个 Windows ACL 集成待验。
- `task3b-focused-green.log`：较早的外部+核心安装专项 48 项，45 通过、3 跳过；后续新增两个检查在最终全量中运行。
- `task3b-vendor-recovery.log`：复制后的案例源码运行既有恢复和 server 三步相关 48 项，全部通过；依赖使用本机已有 SDK1 包，合成文件/transport，显式禁止网络。两项原 SDK缓存/路径子进程测试仍在全量中跑原路径，未把它们伪装成 vendor 验证。
- `task3b-bb-red.log`：首个 Node 命令因 PATH 无 node 没有执行，不能计作行为红证据。改用已知随应用 Node 后，`task3b-bb-before-confirmation.log` 对原件执行真实函数，1 项既有保护通过、4 项新增要求失败；`task3b-bb-green.log` 对补丁副本 5 项全过。这是本机函数/合成依赖检查，原件回验发生在补丁之后，未声称 Windows 原生红绿过程。
- `task3b-archives.log`：真实固定 Node/pnpm archive hash、受限解包及必需文件核对通过，没有执行 Windows 程序。
- `task3b-payload-contract.log`：52 个 vendor 文件符合 shared allowed_payload，未发现链接。
- `task3b-full-final-offline.log`：607 项，595 通过、12 跳过。测试通过 `-c` 启动，patch socket.connect、socket.connect_ex 和 Scrapling Fetcher.get。日志 URL/响应是夹具，不是采集。本轮测试之后仅删除两个未用标准库 import 和案例副本因默认路径改造产生的未用 Path import，再跑 22 项专项通过；源哈希已记录该清理后的最终版本。

## Windows 目标机尚需执行

SDK1/SDK2 实际隔离安装与导入；原生私有 ACL 保存、换证、拒绝宽泛权限；真实 Codex 两片段导入和案例正常登录后的原 `rmfyalk_check_token` 三步。国家库仍应 blocked。

Node/pnpm 冻结安装、bb 实際依赖解析、PowerShell 5.1/CIM/签名/官方版本查询、专用 browser 的启动和 PID/端口识别、断线及端口冲突拒绝、真实网页读取。当前严格命令行身份对比须在 Windows 确认；不匹配会拒绝，不放宽成日常浏览器回退。Playwright/Patchright 1.63 当前官方列 Windows 11+，仍是 Windows 10 待验能力。

本任务未重新执行 Task3A 的真实计划任务（从未有 Windows 连接），也未做 LibreOffice/DOC 或重登录验收。

## Task4 打包交接

把新增根 Python、blocked 脚本、两项测试、文档及整个本轮受限 vendor 文件清单纳入外层 manifest。保留两个 Windows 锁文件、固定 Python/Node/pnpm archive、两组 wheels。不要递归打包 verification，那里含测试日志/快照；vendor/provenance 中明确保留的有限源码溯源文件可以打包。

源文件 ROOT 必须在最终 target 根；SDK1 固定 `.venv-mcp1/Scripts/python.exe`，连接入口均自动按自身定位。旧恢复测试的 Mac `.python-deps`/绝对路径迁移由 Task4 完成；本轮新增测试可在目标 SDK1 环境找到 dotenv，无需原 Mac 目录。`tests/windows_bb_boundary.mjs --before` 仅用于本机历史回验，交付目标使用不带参数版本。

Windows Skill 副本应引用 `docs/windows-external-setup.md` 的实际命令，删除旧机器已登录状态及 `.env`/环境 token 回退指导。宿主导入仍由目标机本人操作；Obsidian 仅保留原可选指定 vault 接口。

建议主代理记忆更新：Task3B 工程与合成回归完成，607/595/12；副本案例48项和JS边界5项通过；Windows原生/账号/浏览器/宿主仍pending，Task4包装和Skill移植未完成。不要记录凭据或把源码通过写成目标机通过。
