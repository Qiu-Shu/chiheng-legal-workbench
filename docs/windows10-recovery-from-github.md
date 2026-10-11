# 从 GitHub 恢复到 Windows 10，并继续工程

2026-10-11。适用于 Windows 10 x64（Intel/AMD），建议 22H2；Windows ARM 不适用。

本次提供代码仓库和单独的工程恢复包。恢复包包含现有公开法库和离线安装资产；Windows 原生安装、ACL、计划任务、浏览器和宿主连接仍待新电脑验收。Task 4 的跨平台测试夹具问题尚未修复。不要据此直接投入真实案件或把测试失败改成通过。

## 一、下载哪些文件

登录有权访问 `Qiu-Shu/chiheng-legal-workbench` 的 GitHub 账号，打开仓库 Releases 中的 `win10-recovery-2026-10-11`。这是私有仓库的预发行附件，不是公开发布。

下载以下附件到同一目录，例如 `C:\Chiheng\Downloads`：

- `chiheng-win10-recovery-2026-10-11.zip`：公开法库、Windows 安装器、源码副本、Skill/插件、运行时、离线 Python 依赖。
- `SHA256SUMS.txt`：总包摘要。
- `asset-manifest.json`：本轮包大小、资料数量、校验结果与排除项。
- `Windows10-恢复与继续工程.md`：本文的独立副本。

GitHub 自动生成的 `Source code (zip)` 只含 Git 文件，不含上述恢复包；不能只下载它。代码基线为 `519d1ba741f58a02107002c2055c63906c58f828`，后续恢复说明提交不改变该代码基线。

总包大小 **255545665 字节**，SHA-256：

```text
bd1ae6a1a40aea8d710ef9cb7662938ada49e16d904ecba437984d3eb3f995f3
```

本包含 49 个入库版本、49 条来源记录、100 条审计记录；镜像为 2190 版本、77809 文本单元。镜像始终为 unverified_mirror，49 个版本的人工审核发布数为 0；可检索不等于已核验现行有效。现有资料全量迁移不等于全国法律全覆盖。

包含 Windows Python 3.13.16、Node 22.23.3、pnpm 11.25.0，以及主环境 79、外部 SDK1 环境 31、测试环境 1 个 wheel 文件。浏览器依赖仍需按锁定版本联网恢复。Codex/其他宿主、Git、浏览器、Obsidian、LibreOffice 的 Windows 安装程序不在包内，按需要通过官方渠道安装；不复制 Mac 软件来充当 Windows 软件。

## 二、核验和解压

打开 Windows PowerShell，运行：

```powershell
$zip = 'C:\Chiheng\Downloads\chiheng-win10-recovery-2026-10-11.zip'
$expected = 'bd1ae6a1a40aea8d710ef9cb7662938ada49e16d904ecba437984d3eb3f995f3'
if ((Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
    throw '文件摘要不符：停止，重新下载，不要运行安装器。'
}
$unpack = 'C:\Chiheng\Package-20261011'
if (Test-Path -LiteralPath $unpack) { throw '解压目录已存在，请换一个新目录。' }
Expand-Archive -LiteralPath $zip -DestinationPath $unpack
```

完整解压后进入 `C:\Chiheng\Package-20261011\持衡 Windows10 个人迁移包`。不要在压缩包预览窗口里运行程序，不要改包内文件或跳过校验。路径过长导致失败时换短目录，不要先全局改注册表。

## 三、恢复可运行目录

双击解压目录中的 `install.cmd`。安装路径选一个不存在的新目录，例如 `C:\Chiheng\legal`；若无写权限，使用安装器给出的当前用户默认目录。不要覆盖已有法库。

安装器会校验完整包、恢复公开数据、创建新的 Windows 环境，并生成本机路径配置。它不依赖旧 Mac 上的 Python，不复制旧 `.venv`。

看到自启动 `[Y/n]` 时，回车/Y 表示按您的要求启用当前用户登录启动和每五分钟调度检查。N 仅安装，便于先做隔离验收。自启动不会保存 Windows 密码；未获网站访问权仍会失败，不会因此绕过登录或网站限制。

安装后检查 `C:\Chiheng\legal\verification\install\state.json`。核心成功与外部组件状态分开记录。失败时保留目录和记录交给 Codex，不在失败目录反复覆盖，不把 ACL、依赖或真实网站错误当作可忽略的测试夹具问题。

PowerShell 检查命令（路径按实际修改）：

```powershell
$target = 'C:\Chiheng\legal'
Set-Location -LiteralPath $target
& "$target\.venv\Scripts\python.exe" -B -X utf8 scripts/install_windows.py --target $target --doctor
```

`doctor` 结果仍需逐项阅读，尤其是 PDF、DOC、外部连接、浏览器和自启动；单个返回码不表示所有能力完成。自启动启用后还要实际注销并重新登录，验证服务和任务运行。

## 四、连接宿主、Skill 和 Obsidian

安装后的 `verification\install\codex-mcp.toml` 是主法库连接片段，`codex-external-mcp.toml` 是外部连接片段。让新电脑上的 Codex/兼容 MCP 宿主读取它们，按实际宿主能力合并，不覆盖其他连接、不注册重复名称。若该宿主在 Windows 10 不受支持，保留工程与命令行环境，不宣称宿主已接通。

主法库用 `.venv\Scripts\python.exe`，外部案例客户端用 `.venv-mcp1\Scripts\python.exe`，不要混装两种 MCP SDK。HTTP 插件需实际监听 `127.0.0.1:18063`；只在本机开放。不要把 localhost 改成公网监听来接 ChatGPT。

导入安装目录 `skills` 下的持衡、萌律和 Scrapling Skill。这是 Windows 专用副本；仓库根 `skills` 保留原 Mac 版，不能混用固定路径说明。至少验证：检索一个法源、读取来源卡和原文、运行一个合成模拟法庭会话。不要用真实案卷作首次安装测试。

Obsidian 可先手动打开包内两页 `memory` 项目导航。需要动态法库看板时，指定新机自己的 vault 路径，让 Codex 使用已有 `scripts/export_obsidian_library.py` 配置导出；不要照搬旧 Mac 路径，不把案卷写进公开法源目录。整个私人 vault 未上传。

## 五、新机重新登录

本包不含案例网站、企查查、天眼查或 GitHub 凭据，不含浏览器登录状态。本人在新电脑正常登录；验证码和会员权限仍由本人处理。

人民法院案例库凭据按 `docs/windows10-migration-guide.md` 的隐藏输入流程在本机保存，不贴进聊天、GitHub 或 Obsidian。必须在当前宿主依次验证认证、检索、正文读取，不能以“页面显示登录”代替可用性验证。失效时提示本人重新登录。

国家法规客户端的 FLK_ACCESS_BLOCK 继续保留；浏览器只接专用实例，未知旧状态停止并人工检查。详安装目录 `docs/windows-external-setup.md`。本包不包含商业 API 授权。

## 六、建立单独的代码续建目录

运行目录用 `C:\Chiheng\legal`，源码目录用 `C:\Chiheng\src`，避免调试直接改动自动运行的法库。安装 Git 后，通过 GitHub 正常浏览器授权克隆：

```powershell
git clone https://github.com/Qiu-Shu/chiheng-legal-workbench.git C:\Chiheng\src
```

没有 Git 时可先在网页下载代码 ZIP并打开工程，但这不含 Git 历史；后续提交前应建立正常克隆。GitHub 密码或令牌不要放在命令参数和聊天里。

让 Codex 先读 `HANDOFF.md` 和 `verification/windows10-2026-10-11/task4-spec-review.md`。先检查当前 Windows 版本、Git 状态和已恢复资产，再继续 Task 4。

### 源码测试所需数据

源码目录的 `data` 被 Git 排除。要在源码目录运行完整检查，必须另建开发用数据副本；不能指向正在更新的生产目录。以下步骤仅针对新建且没有 `data` 的克隆：

```powershell
$ErrorActionPreference = 'Stop'
$code = 'C:\Chiheng\src'
$target = 'C:\Chiheng\legal'
$bundle = 'C:\Chiheng\Package-20261011\持衡 Windows10 个人迁移包'
$stage = 'C:\Chiheng\dev-data-20261011'
if (Test-Path -LiteralPath "$code\data") { throw '源码目录已有数据，停止，先核对。' }
if (Test-Path -LiteralPath $stage) { throw '数据恢复中转目录已存在，停止。' }
if (Test-Path -LiteralPath "$code\vendor\treasury\sources\china-law\laws") { throw '镜像目录已存在，停止。' }
& "$target\.venv\Scripts\python.exe" -B -X utf8 "$code\scripts\transfer_library.py" restore --archive "$bundle\data\personal-public-library.zip" --target $stage
if ($LASTEXITCODE -ne 0) { throw '数据恢复失败，停止。' }
Move-Item -LiteralPath "$stage\data" -Destination "$code\data"
Copy-Item -LiteralPath "$bundle\vendor\treasury\sources\china-law\laws" -Destination "$code\vendor\treasury\sources\china-law\laws" -Recurse
```

这里只移动新恢复的开发副本，不动运行目录。Git 中的 shared-library 配置指向 vendor 镜像，上述步骤补齐它；原件与 SQLite 在源码 `data` 中。保留中转目录剩余的清单/配置作证据，不覆盖克隆的配置。

安装可选测试 wheel 并运行定向检查：

```powershell
Set-Location -LiteralPath $code
& "$target\.venv\Scripts\python.exe" -m pip install --no-index --no-deps --require-hashes --find-links "$bundle\runtime\wheels-dev" -r requirements-windows-dev.lock.txt
if ($LASTEXITCODE -ne 0) { throw '测试依赖安装失败。' }
$env:CHIHENG_TEST_SDK1_SITE = "$target\.venv-mcp1\Lib\site-packages"
& "$target\.venv\Scripts\python.exe" -B -X utf8 -m unittest discover -s tests -p 'test_windows*.py'
```

以上借用已恢复的 Windows 解释器，在源码目录测试；SDK1 单独指定，不把它永久写进 PYTHONPATH。长期开发可依照锁文件另建两个开发环境，不复制现有 `.venv`。

全套测试还需由源码 `skills/cn-litigation-redteam` 生成 `dist/cn-litigation-redteam.zip`，方法见 HANDOFF.md；不要拿 Windows Skill ZIP 冒充 Mac 源码版。然后运行 `scripts/test_windows_offline.py`。已知 Task 4 平台夹具会报错，应按审查意见修复并保留失败证据。跳过原生用例不等于通过。

## 七、下一轮工程顺序

1. 修复 Task 4 的跨平台夹具：getuid、权限断言、link/rename 故障注入、本机可执行路径、符号链接权限，以及普通法庭测试目录的 ACL 准备。不整套跳过法庭测试。
2. 定向红绿测试、全套离线检查、浏览器 JS 边界检查；每项写明实际操作系统和跳过原因。
3. 重新生成包，在新目录恢复并核对全部原件、数据库逻辑摘要与来源卡，再做规格/质量审查。
4. 完成 Task 5 的 Windows 10 实机安装、ACL、锁、计划任务、重新登录启动、宿主 MCP、网站三步验证、浏览器与 PDF/DOC 转换。
5. 提交代码和测试记录前先检查 Git 状态，确保 data、private、.env、浏览器 profile 和运行时未被加入 Git。公开法库后续更新继续使用私有附件并保留版本、来源和哈希。

全国来源覆盖、企业信息 API、ChatGPT 云端入口和真实法律效果验收仍是独立待办，不因本次迁移完成而视为完成。

## 本轮验证范围

新包在 Mac 上完成外层 452 个文件核验、内层 590 个公开资料载荷恢复与逐文件哈希核验，以及全部 49 个版本的来源卡生成。数据库逻辑摘要与导出相同，镜像标记未改变。Windows 10 上的本文操作尚待执行，不能据这些结果宣称实机成功。

本轮从新包恢复目录执行完整离线检查：619 项，607 通过、12 项原生待验跳过，耗时 19.387 秒；JS 浏览器边界检查 12 项通过。解释器和 SDK1 测试依赖借用本机既有 Mac 环境，没有宣称全新 Windows 环境通过。

技术存放依据：[GitHub 大文件说明](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)建议大文件通过 Releases 分发；[Release 附件限制](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)允许本包大小。本仓库继续保持私有。
