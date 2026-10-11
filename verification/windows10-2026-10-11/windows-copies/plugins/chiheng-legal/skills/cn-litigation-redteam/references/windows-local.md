# Windows 本机运行

先从用户实际选定的安装目录读取 `verification/install/state.json`，核对 `target` 与真实目录一致；分别查看核心、外部组件、自启动和宿主状态。没有记录时报告尚未安装，不使用旧 Mac 路径推测。

主法库和模拟法庭用 `$target\.venv\Scripts\python.exe`；案例库用 `$target\.venv-mcp1\Scripts\python.exe`。不得混用两个 MCP SDK 环境。

仅处理用户本次指定材料。案件目录必须新建，父目录须已存在。用现有 helper 创建受保护 ACL，拒绝共享目录、链接、所有者或权限异常，不修改既有用户目录权限。下例的路径先替换为本次实际值：

```powershell
$target = 'C:\Chiheng\legal'
Set-Location -LiteralPath $target
$py = Join-Path $target '.venv\Scripts\python.exe'
$rehearsalRoot = 'C:\Chiheng\本次演练'
& $py -X utf8 -c "import sys; from windows_private import private_directory; private_directory(sys.argv[1], create=True)" $rehearsalRoot
if ($LASTEXITCODE -ne 0) { throw '私有目录未通过检查，停止' }
```

仅复制本次指定 UTF-8 文本进新目录；普通文件须继承受保护 ACL，程序还会核验文件安全属性、大小及字节哈希，硬链接也拒绝。登记每份材料的唯一 ID、目录内相对路径和实际 SHA-256。案件包和单回合 JSON 使用 UTF-8 无 BOM；PowerShell 5 的 `Set-Content -Encoding UTF8` 会写 BOM，改用 `[IO.File]::WriteAllText($packetFile, $json, (New-Object Text.UTF8Encoding($false)))`。各变量须赋本次实际路径，示例不代表材料已生成。

```powershell
& $py -X utf8 scripts/mock_hearing_session.py init --case-root $rehearsalRoot --input $packetFile
& $py -X utf8 scripts/mock_hearing_session.py read --case-root $rehearsalRoot
& $py -X utf8 scripts/mock_hearing_session.py append --case-root $rehearsalRoot --input $turnFile
& $py -X utf8 scripts/mock_hearing_session.py append-law --case-root $rehearsalRoot --input $lawTurnFile
& $py -X utf8 scripts/mock_hearing_session.py progress --case-root $rehearsalRoot
& $py -X utf8 scripts/mock_hearing_session.py rehearse --case-root $newRehearsalRoot --previous-case-root $rehearsalRoot --input $newPacketFile
```

每次检查退出码，失败不得继续追加。复练新目录也先准备私有 ACL。[原模拟法庭规则](mock-hearing.md)的阶段、审计、逐争点追问、来源回执、完成后禁止追加、关联复练和真实审批要求全部保留。

Skill 需手动导入实际宿主。主 MCP 片段在 `verification/install/codex-mcp.toml`，外部片段在 `verification/install/codex-external-mcp.toml`。注册、可调用、实际数据可用分别验证；插件本机 HTTP 地址不代表云端自定义 GPT 已接通。

新机案例库先本人正常登录官网，再用独立解释器运行 `windows_case_access.py --save-local`，认证值只写 `$target\private\case-access.env`。不带旧凭据或 profile。当前宿主必须完成认证、一条检索、对应正文三步才报告可用。国家法律法规数据库仍优先作为官方核验来源，但 `windows_flk_blocked.py` 返回 blocked 时停止该路线，不绕过封锁；离线镜像只作待核线索。
