# Windows 10 外部组件使用

核心安装完成后，先查看 `verification/install/state.json` 的 `external` 项。`status=complete` 仅指核心检索、PDF 和模拟法庭的安装检查完成。国家库自动访问保持 blocked；案例库需本人重新登录；浏览器和宿主导入均需目标机核对。

以下 PowerShell 示例把安装目录写作 `D:\持衡`，请改为实际目录。目标目录可以包含中文和空格。

```powershell
$InstallRoot = 'D:\持衡'
& "$InstallRoot\.venv\Scripts\python.exe" -E -s -X utf8 "$InstallRoot\windows_external.py"
```

诊断会分别报告 SDK 1、案例本机认证文件、bb-browser 和宿主同名连接。不会联网验证真实账号。安装失败会记录组件与阶段，例如 `mcp1.offline_pip`、`browser.frozen_dependencies`；不保存子进程可能带有私密内容的原始输出。请保留现有失败目录，核对缺失文件或网络后使用新的安装目录重装，程序不会自动修补旧安装。

## 案例库

外部 SDK 固定为 MCP 1.28.0，独立目录是 `.venv-mcp1`。主 `.venv` 继续使用 MCP 2。认证唯一来源为本安装 `private/case-access.env`；vendor 的 `.env` 和环境 token 均不作认证回退。不要把旧电脑凭据或浏览器 Cookies 搬入新电脑。

本人先正常登录 [人民法院案例库](https://rmfyalk.court.gov.cn/)，再在本机控制台保存必要认证值。该输入不回显，不通过聊天提供，不写诊断日志；不含自动提取网页登录 Cookies、登录或验证码绕过。

```powershell
& "$InstallRoot\.venv-mcp1\Scripts\python.exe" -E -s -X utf8 "$InstallRoot\windows_case_access.py" --save-local
& "$InstallRoot\.venv-mcp1\Scripts\python.exe" -E -s -X utf8 "$InstallRoot\windows_case_access.py" --status
```

保存入口用私有 ACL 创建目录和文件，遇到既有宽泛权限、链接或异常对象会拒绝，不自动修复既有权限。写入失败保留旧文件。`saved_pending_auth_search_body` 只表示本机值通过格式检查。导入下节连接后，通过当前 MCP 的 `rmfyalk_check_token` 完成原有的账号认证、单条检索、该条正文读取；三步通过且认证值未变化才表示该次网站可用。失效后重新正常登录并用同一保存入口更新文件，原客户端逐次重读。

## 宿主连接

`verification/install/codex-external-mcp.toml` 是独立的两个连接片段。命令指向最终安装目录的 `.venv-mcp1\Scripts\python.exe`。案例入口为 `windows_case_access.py`，国家库入口为 `scripts/windows_flk_blocked.py`，后者会明确返回 blocked 并退出，不自动请求官网。

诊断只检查目标机默认 `.codex/config.toml` 中的连接名称，输出冲突名称。自定义宿主位置可显式检查：

```powershell
& "$InstallRoot\.venv\Scripts\python.exe" -E -s -X utf8 "$InstallRoot\windows_external.py" --host-config 'D:\配置\config.toml'
```

存在同名连接时先由本人核对，不能覆盖导入。无冲突也仍需本人在目标机宿主导入、启用并实际测试；安装器不拷贝整份 Codex 配置，不把片段已生成计为宿主已连接。Skills 和 Obsidian 继续沿用总迁移说明；这里只使用安装器已有的指定 vault 入口。

## 专用浏览器

bb-browser 依赖重建需要目标机联网，采用随包固定 Node/pnpm、冻结锁和禁用生命周期脚本。不会使用 Mac node_modules，不下载旧 Chrome。

先运行以下入口，让程序从 Windows 常规安装位置寻找 Chrome/Edge；也可显式给出浏览器路径。启动前核对文件签名、产品身份，并从官方发布元数据核对当前稳定版本。无法核对或版本过旧时返回 pending，需先更新本机浏览器。两个版本元数据源为 [Chrome VersionHistory](https://versionhistory.googleapis.com/v1/chrome/platforms/win64/channels/stable/versions?pageSize=1) 与 [Edge 更新元数据](https://edgeupdates.microsoft.com/api/products?view=enterprise)。

```powershell
& "$InstallRoot\.venv\Scripts\python.exe" -E -s -X utf8 "$InstallRoot\windows_browser.py" --start-browser
# 显式路径示例：
& "$InstallRoot\.venv\Scripts\python.exe" -E -s -X utf8 "$InstallRoot\windows_browser.py" --start-browser --browser 'C:\Program Files\Google\Chrome\Application\chrome.exe'
```

两条启动命令选一条执行。新窗口使用本安装的私有 `private/browser-profile`，固定 CDP 为 `127.0.0.1:19224`，daemon 固定默认本机端口为 19824。占用端口、旧 profile、未知或陈旧 daemon/PID 都会被拒绝，程序不自动清理旧状态或结束外来进程。启动失败保留现场；请核对进程归属和状态后再操作，不要把日常浏览器改成这个端口。

```powershell
& "$InstallRoot\.venv\Scripts\python.exe" -E -s -X utf8 "$InstallRoot\windows_browser.py" -- --version
& "$InstallRoot\.venv\Scripts\python.exe" -E -s -X utf8 "$InstallRoot\windows_browser.py" -- tab list
```

只有单独的 help/version 可以在浏览器未连接时运行。其他调用先验证本安装记录的进程、创建时间、命令和监听端口，再访问固定 CDP；清除 hub 相关环境和 Node 注入项，不回退到日常浏览器。所有受控 CLI 调用最多运行 120 秒；超时只由运行器结束本次 CLI 子进程，保留浏览器、daemon 与现场供身份核对，诊断不输出命令内容或捕获输出。直接运行包内原始 CLI、daemon 或旧 shell 不属于此受控入口。

本轮没有自动清理、重启旧实例的进程管理功能。Windows 的 daemon 即使正常退出也保留状态文件；启动拒绝、端口竞争失败及退出期间状态被替换时同样不删除。关闭浏览器、daemon 或系统重启后，旧状态需要人工核对，不能假定可自动重启。遇到阻断请保留状态文件、profile 及其内容供进程归属复核，不要仅凭报错删除；本工具不提供一键清理。`--openclaw`、实际读取日常浏览器历史的 `site recommend`、尚未迁移的 `site update`，以及顶层 `history` 和 raw daemon 控制在 wrapper 拒绝，包括全局选项前置的写法。

保留 `tab`、`get`、`eval` 及 site 的 `list/info/search/run`、adapter 名称简写；这些仍受固定 CDP 和超时约束。CLI 和 daemon 的 site 目录均位于本安装的 `private/bb-state`，Windows 普通 site 命令不会隐式运行后台更新。社区 adapter 安装、更新、历史推荐和长期命令仍为 pending，不应直接运行旧更新入口规避限制。Windows 10 下其他 bb 子命令、Playwright/Patchright 都尚需实际验证；[Playwright 官方系统要求](https://playwright.dev/python/docs/intro#system-requirements) 当前列 Windows 11+。

目标机合成安全测试：

```powershell
& "$InstallRoot\.venv-mcp1\Scripts\python.exe" -B -E -s -X utf8 -m unittest tests.test_windows_external.WindowsCaseNativeTests -v
& "$InstallRoot\runtime\node\node-v22.23.3-win-x64\node.exe" "$InstallRoot\tests\windows_bb_boundary.mjs"
```

第一条请在安装目录运行。第二条执行真实副本函数与合成依赖，不连接浏览器，不能替代 Windows 实际启动、端口冲突、断开拒绝和实际网页读取检查。
