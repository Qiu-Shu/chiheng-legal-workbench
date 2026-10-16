# Task 2 — Windows 原生夹具与离线回归

日期：2026-10-16。范围为独立持衡仓库；未修改群兴主仓库源码，未提交、发布、启用服务或读取真实私案、凭据。基线 HEAD 为 `9f7d5bb8a5e13e7022dc2704cd2fb4bafeaf8094`。

最终结果（含Standards复核修复）：完整离线 **629项，622通过、7明确跳过，98.974秒，退出0**；浏览器JS边界前次 **12/12通过，退出0**，此次仅连接保护修改未重复运行JS。Windows原生私有文件8项全部实际运行通过，未将历史Mac结果合并计算。

## 环境与资料

- 当前主机 Windows 10 x64 19045，Python 3.13.16；源码目录独立 `.venv` 使用锁定 MCP 2.2.0、pywin32 312、Scrapling 0.4.15、ReportLab 4.4.9。由原隔离安装内已核验的 Python 运行时创建新虚拟环境，没有修改原安装。
- `.venv-mcp1` 通过现有 `windows_external.install_mcp1` 离线安装，真实 import 验证 MCP 1.28.0。主环境不安装 SDK1；测试只临时载入独立环境中的 dotenv，原有双 SDK 隔离测试保留。
- 使用原恢复包的 `personal-public-library.zip` 经 `restore_library` 全部校验后，在短临时目录恢复，再独占复制到源码开发 `data/`。镜像三文件、测试 Skill ZIP、已核验 Node 22.23.3均独立准备；没有覆盖现有公共库。
- 实测开发库版本/索引/来源各49、审计100；镜像2190版本、77809文本单元，仍为 `unverified_mirror`、`coverage_complete=false`。详 `task2-environment.json`。
- 首次向源码 `.local/` 深路径恢复触发 Windows 长路径限制，`FileNotFoundError` 原始证据保留于 `task2-data-restore.log`；短路径恢复成功见 `task2-data-restore-short.log`。深路径支持未在本任务修复。

## 最小修订

- 普通模拟法庭、复练、事实完整性、追问和审计夹具用现有 Windows 私有目录实现；业务断言继续运行。只有 POSIX mode 位检查明确分流，真实 Windows DACL、安全句柄、硬链接及并发保护保持。
- Mac 安装器测试完整模拟 `getuid`，使用本机临时路径；首建故障注入选择 Windows `rename`/POSIX `link`；符号链接仅遇到明确能力/权限缺失代码才 skip，未知错误继续失败。混合链接/重解析点/路径/权限用例拆开，避免一次 skip 吞掉其余断言。
- 修复测试中的 `/bin/sh`、POSIX绝对路径、反斜杠集合、TOML转义和 file URI解码假设；数据库清理前明确关闭连接。
- 固定证据夹具和浏览器 JS补丁/原始来源通过 `.gitattributes` 保留字节。仅恢复15个被CRLF转换的Git原始blob，没有重算预期摘要或改原文。恢复证据见 `task2-byte-fixtures-restored.log`、`task2-provenance-restored.log`。
- 离线入口在 Windows 使用UTF-8并传递给子进程。同步 `socket.connect` 拦截仅允许标准库 `socketpair` 当前调用栈所持有的客户端连接其自身临时监听端口，普通同步连接和 `connect_ex` 被拒绝。Windows 默认异步连接另在 `IocpProactor.connect` 入口拒绝，在调用 `ConnectEx`/`WSAConnect` 前停止；`Fetcher.get` 保留拦截。五项边界测试覆盖普通同步连接、真实默认异步 `open_connection`/`sock_connect`、异步本地任务及内部成对连接。国家库禁止访问测试及其冷启动脚本复用同一保护。

## 运行证据

以下日志均为本机保留的原始日志，受 `.gitignore` 的 `*.log` 排除；本报告不把未运行检查标为通过。

| 运行 | 结果 | 退出码 | 日志 |
| --- | --- | --- | --- |
| 初始六模块 `python -X utf8 -B -m unittest ... -v` | 118项，5 failure、45 error、1 POSIX skip | 1 | `task2-targeted-red.log` |
| 完整性/追问/审计三个关联模块 | 37项，37 error，均为非私有目录 | 1 | `task2-related-red.log` |
| 首次夹具修复后九模块 | 158项，2数据库清理 error、3 POSIX skip | 1 | `task2-targeted-green-attempt1.log` |
| 第一次完整离线 | 622项，170 failure事件（含subTest）、10 error、6 skip | 1 | `task2-full-offline-attempt1.log` |
| 离线连接边界 | 3/3通过 | 0 | `task2-offline-guard-green.log` |
| 第二次完整离线 | 627项，36 failure事件（含subTest）、1 error、7 skip | 1 | `task2-full-offline-attempt2.log` |
| 余项针对性第一次 | 37项，6 error；暴露外部测试依赖dotenv被之前模块预加载 | 1 | `task2-remaining-green.log` |
| dotenv独立加载后余项针对性 | 37/37通过 | 0 | `task2-remaining-green-attempt2.log` |
| 第三次完整离线，无预设UTF-8环境 | 627项，620通过、7明确skip，82.580秒 | 0 | `task2-full-offline-attempt3.log` |
| Standards复核追加Proactor绕过回归 | 2项，2 failure；真实本机连接未被拒绝 | 1 | `task2-proactor-red.log` |
| Proactor修复后边界及国家库冷启动 | 14/14通过 | 0 | `task2-proactor-green.log` |
| Proactor修复后完整离线，无预设UTF-8环境 | 629项，622通过、7明确skip，98.974秒 | 0 | `task2-full-offline-after-proactor-review.log` |
| Node `tests/windows_bb_boundary.mjs` | 12/12通过，无实网/真实浏览器 | 0 | `task2-js-boundary.log` |

完整入口复跑命令（PowerShell，工作目录为本仓库）：

```powershell
Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue
& './.venv/Scripts/python.exe' -B scripts/test_windows_offline.py
```

主依赖、dev依赖、SDK1安装均退出0，分别记录 `task2-main-deps.log`、`task2-dev-deps.log`、`task2-sdk1-deps.log`。`git diff --check` 退出0。

## 保留边界

真实 LibreOffice DOC转换未验；Mac textutil、POSIX mode/owner/FIFO/flock在本Windows不执行。当前机器允许创建符号链接，相关拒绝用例实际运行，没有以能力缺失skip。Task4的新源码一致候选、清洁安装和独立复核，以及Task5的宿主连接、真实网站认证/检索/正文、计划任务/重登录仍由后续任务完成。本记录不是生产验收或法律材料审核完成。

7项跳过为：`test_hearing_rehearsal`与`test_mock_hearing`的2项POSIX目录mode检查；`test_rmfyalk_recovery`的2项POSIX open flags、FIFO/mode/owner检查；`test_windows_portability`的1项POSIX flock互通；`test_legacy_doc`的1项Mac textutil转换、1项缺LibreOffice的真实DOC转换。

### Standards复核修正

先前627项通过并未覆盖Windows默认Proactor绕过，不能据此证明异步连接也被阻断。独立审阅使用仅绑定127.0.0.1的临时监听器复现该缺口；本任务补2项真实连接RED并在Proactor连接入口修复。审阅者随后独立确认原探针被拒绝、监听器未收到连接，socketpair仍可传递合成串；其相关58项结果为57通过、1 POSIX skip、退出0，与本任务运行分别记录。

测试保护限定于当前Python测试进程常用TCP、asyncio和Fetcher入口，**不是系统级联网沙盒**。DNS、UDP sendto、原生客户端及未注入该保护的子进程没有全面封禁；不得将测试入口称为“所有网络均已阻断”。本轮绕过复现与复验均只使用临时本机监听器，没有外网探测。
