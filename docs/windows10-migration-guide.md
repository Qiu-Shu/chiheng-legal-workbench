# 持衡与萌律 Windows 10 个人迁移说明

适用目标为 Windows 10 x64（Intel/AMD），推荐 22H2。当前包在 Mac 上完成打包、完整性与恢复测试；Windows 原生安装、权限、PowerShell、真实账号、浏览器及宿主连接仍须在目标机验收。Windows ARM 不适用。

## 安装

1. 将 ZIP、SHA256.txt、内容清单.json 和本说明一起复制到目标机。在 PowerShell 执行 `Get-FileHash -Algorithm SHA256 -LiteralPath '总包的完整路径.zip'`，将结果与 SHA256.txt 对照。应与交付方提供的摘要一致；包内清单用于发现损坏，不能单独证明发布者身份。
2. 完整解压 ZIP，打开“持衡 Windows10 个人迁移包”目录，双击 `install.cmd`，不要直接在压缩包里运行。保留完整解压目录，后续测试需要其中的 wheel 文件。
3. 选择一个新的安装目录。可按回车使用当前用户 LOCALAPPDATA 下默认目录，也可选更短的 `C:\Chiheng\legal`，前提是有权限。已有目标或名称冲突会拒绝覆盖，请另选新目录。旧 Windows 长路径设置可能使深层依赖安装失败；先使用短目录，不自动改注册表、代理或系统全局执行策略。[微软路径限制说明](https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation)
4. 看到自启动 `[Y/n]` 时自行选择：回车或 Y 为当前用户登录后启动本机检索，并每五分钟运行现有更新调度检查；N 只安装。计划任务不保存 Windows 密码。更新检查不保证官网采集成功，既有封锁继续保留。
5. 查看分项结果。实际安装记录在目标目录 `verification/install/state.json`。核心成功不表示案例库、浏览器、宿主或重新登录启动已通过。失败时保留目录和记录，不在失败目录上重复覆盖。

安装器不默装 Codex、Obsidian、未知浏览器或 LibreOffice。现有程序路径如需设置，应由本人确认；不迁移浏览器 profile 或登录状态。浏览器依赖按冻结锁联网重建，因此此包的核心恢复可离线，浏览器安装不能宣称全离线。Playwright 当前官方支持范围未承诺 Windows 10，目标机结果须单列。

## 导入 Skill 和连接

安装后的 `skills` 含持衡、萌律法律宝典和依赖 Scrapling 官方 Skill。按实际宿主支持的方式手动导入，不因文件已复制就称宿主已启用。持衡和萌律为 Windows 专用副本，原法律分析、事实状态、自认与律师审批规则保留。

主法库 stdio 配置在 `verification/install/codex-mcp.toml`，外部 MCP 配置在 `verification/install/codex-external-mcp.toml`。使用实际目标路径，避免覆盖宿主同名连接；正常重建连接后检查工具发现和实际调用。主法库使用 `.venv\Scripts\python.exe`，外部案例库使用 `.venv-mcp1\Scripts\python.exe`，不要混用。

`plugins/chiheng-legal` 保留原插件身份和本机 HTTP 接入方式。HTTP 需要本机服务实际监听 `127.0.0.1:18063`；stdio 片段直接启动对应进程。按宿主选择一种适合的主法库连接，不重复注册冲突名称。本机 localhost 可用不代表云端自定义 GPT 已接通，本包没有上传账号或发布云服务。

## 案例库和浏览器

在目标机本人正常登录人民法院案例库，完成网站验证后，在 PowerShell 使用实际安装目录执行：

```powershell
$target = 'C:\Chiheng\legal'
Set-Location -LiteralPath $target
& "$target\.venv-mcp1\Scripts\python.exe" -X utf8 windows_case_access.py --save-local
& "$target\.venv-mcp1\Scripts\python.exe" -X utf8 windows_case_access.py --status
```

认证值在本机隐藏输入，只保存到 `private\case-access.env`，不贴入聊天或 Obsidian。不从旧 .env、环境变量、原 Mac 登录或日常浏览器隐藏数据回退。状态只表示本地文件情况；须由当前宿主的 `rmfyalk_check_token` 完成认证、一条检索、对应正文三步，全部通过才能说网站实际可用。国家库 `windows_flk_blocked.py` 保留 blocked，不改用旧入口绕过。

受控浏览器操作、指定浏览器、端口与旧状态人工复核见 `docs/windows-external-setup.md`。本人在新专用浏览器正常登录。浏览器退出后遗留状态须人工核对，不自动清理、接管日常浏览器或杀其他进程。

## 资料、记忆与许可

`data/personal-public-library.zip` 保存当前公开资料、原件、审核/来源记录和离线镜像。数量以内容清单和恢复后的健康检查为准。quarantine 表示未经人工法律复核，unverified_mirror 只作线索；完整迁移现有内容不表示全国法律已全覆盖。引用须展示来源、链接、版本、定位、时间、缺失字段及原文。未知日期不补造，withdrawn 不作正常依据。

`memory` 只有本项目导航与当前摘要，可由本人放入选定 Obsidian vault；本包没有整库、全局钩子、私人案卷或本机配置。公开资料导出到 Obsidian 的路径需在新机自行确认，不沿用 Mac 路径。

来源和许可见 `delivery-docs/component-sources.md`、`delivery-docs/runtime-sources.md`、各 Skill LICENSE/NOTICE、vendor 来源页和 wheel 内许可。china-law 的历史本地 README 许可徽章与现上游许可不一致，相关个人已有副本随迁，未声称公开再分发许可已完成。

## 离线测试与真实验收

如需重跑包内全套离线工程测试，先在安装后的主环境加入包内可选 ReportLab 测试依赖。下例 `$bundle` 是完整解压目录，`$target` 是已安装目录。此开发依赖不是核心启动前提。

```powershell
$bundle = 'D:\迁移\持衡 Windows10 个人迁移包'
$target = 'C:\Chiheng\legal'
Set-Location -LiteralPath $target
& "$target\.venv\Scripts\python.exe" -m pip install --no-index --no-deps --require-hashes --find-links "$bundle\runtime\wheels-dev" -r requirements-windows-dev.lock.txt
& "$target\.venv\Scripts\python.exe" -B -X utf8 scripts/test_windows_offline.py
& "$target\.venv-mcp1\Scripts\python.exe" -B -X utf8 -m unittest tests.test_windows_external.WindowsCaseNativeTests -v
& "$target\.venv\Scripts\python.exe" -B -X utf8 scripts/install_windows.py --target $target --doctor
```

主套件的 vendor 夹具只临时加载本安装独立 MCP1 环境，并保留两个 SDK 隔离测试；POSIX 权限/FIFO与Windows ACL分别报告，跳过不算通过。浏览器 JS 边界测试用安装内 Node 执行 `tests/windows_bb_boundary.mjs`（不加 `--before`）。

目标机还须验证中文含空格目录、原件哈希、来源卡和镜像检索、私有 ACL 拒绝、完整合成模拟法庭、计划任务及重新登录启动、真实宿主 MCP、案例三步、浏览器与实际 PDF/DOC 转换。所有结果分项记录；没有测试的能力保持待验。
