# Windows 10 本机配置

先确认用户实际安装目录，读取其 `verification/install/state.json` 并核对 `target`。示例 `C:\Chiheng\legal` 必须替换为已核对目录。核心、外部组件、宿主导入与账号验证分别检查，旧 Mac 登录结果不能证明新机已登录。

```powershell
$target = 'C:\Chiheng\legal'
Set-Location -LiteralPath $target
$py = Join-Path $target '.venv\Scripts\python.exe'
$casePy = Join-Path $target '.venv-mcp1\Scripts\python.exe'
& $py -X utf8 scripts/install_windows.py --target $target --doctor
& $casePy -X utf8 windows_case_access.py --status
& $casePy -X utf8 windows_case_access.py --save-local
```

主法库使用 MCP 2 主环境，案例库使用 MCP 1.28.0 独立环境。手动导入 `verification/install/codex-mcp.toml` 和 `verification/install/codex-external-mcp.toml` 中对应片段，正常重建宿主连接后验证工具。独立脚本成功不能代替当前宿主连接成功；Skill 和插件也需手动导入。

## 案例认证

`--save-local` 只接收本人已取得的单个 RMFYALK_TOKEN 原始值（客户端请求头名为 `faxin-cpws-al-token`）；输入时不要加 `RMFYALK_TOKEN=`、引号或整段 Cookie。程序不提供网页登录或自动取值功能，不编造官方导出入口。仅在本人已经合法取得该值后保存；尚无该值就停在待设置，不读取隐藏凭据替代。

本人正常登录 [人民法院案例库](https://rmfyalk.court.gov.cn/)，完成网站验证。认证值只在本机终端通过上述 `--save-local` 隐藏输入，唯一保存位置为 `$target\private\case-access.env`，由程序准备私有 ACL。不得贴入聊天、Obsidian、云端或迁移包，不读取浏览器隐藏凭据，不使用旧 .env 或环境变量回退，不绕过验证码。

`--status` 只显示本地状态，不能证明线上可用。用户本地更新后，使用当前宿主注册的 `rmfyalk_check_token` 完成认证、检索一条案例、读取对应正文三步。全部通过才报告“网站实际可用”。文件非空、HTTP 200、网页已登录或旧 Mac 于 10 月 5 日成功都不算新机通过。凭据变更由正常调用重读；更新代码后仍须确认宿主已加载新版本。

过期或官网明确拒绝认证时提示本人重新登录；网络、TLS、接口、文件安全错误分别报告，不能全部归为过期。等待有效凭据时不凑案例。案例条目正文不等于原裁判全文；来源链接、观点定位、适用性另行核对，会员资格不等于 API、批量获取或转授权许可。

## 官方法规与其他组件

`FLK_ACCESS_BLOCK` 是现有程序的封锁策略名称，不是要求用户新增或切换的配置项。

国家法律法规数据库仍优先作为官方核验来源。当前片段的 `scripts/windows_flk_blocked.py` 保留既有封锁；返回 blocked 时停止此路线，不启动旧 vendor server、旧 HTTP 服务或更换身份绕过。保留待核状态，可使用已获授权的官方公开页面或请求原文，不把镜像升级为官方核验。

本包没有安装商业凭据、元典、北大法宝、天眼查及其他完整律师工作流。按需另行确认许可与实际安装后使用。共享法库无需会员密钥，不读取私人案件目录。

本机 HTTP 插件地址为 `http://127.0.0.1:18063/mcp`，该地址和本机 stdio 片段均不证明云端 ChatGPT 或自定义 GPT 已接通。浏览器通过 `$py windows_browser.py --start-browser` 使用用户已安装并确认的浏览器；不迁移登录/profile，细节看安装内 `docs/windows-external-setup.md`。
