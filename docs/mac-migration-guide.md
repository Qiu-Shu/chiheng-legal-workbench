# 换一台 Mac：个人法库迁移与登录启动

本流程面向 Apple Silicon Mac（原生 arm64），将公开法库和程序装到一个全新目录。保留原件、来源、审核及撤回状态；镜像仍是未核验线索。整个资料库不因此成为完整或现行有效的法律库。

## 准备什么

- 程序文件包：项目根目录的 Python 文件、`scripts/` 内 Python 文件和 `requirements*.txt`。不要复制旧 `.venv`。
- 用 `scripts/transfer_library.py` 导出的个人迁移 ZIP。它含数据库、公开原件、镜像、来源配置、审核记录和调度状态；不打包账号、密钥、机器运行配置或整个 Obsidian vault。历史留证中的旧文件路径可能保留，但不作为新电脑的运行路径。
- 新 Mac 上能运行的原生 Python 3.12+，或带有配套 Python 的当前 Codex。安装脚本自身也需要 Python 启动，不能在完全没有 Python 的机器上直接双击完成。自动发现依次检查当前 Python、Codex 常用配套路径和 PATH；找不到时用 `--python` 指定。
- 安装依赖需要联网。SQLite 必须支持 FTS5/trigram，脚本会运行所选 Python 实测，再检查新建环境。

LibreOffice、国家库官方接口客户端、浏览器程序和账号授权不会随数据 ZIP 自动复制。需要旧 DOC 转换时先安装 LibreOffice；需要定时更新时另行准备国家库客户端及其依赖。浏览器安装单独按 Scrapling 官方说明处理，不从旧机器复制浏览器缓存。

## 1. 在旧 Mac 导出

在现有项目根目录执行，ZIP 路径必须尚不存在：

```sh
.venv/bin/python scripts/transfer_library.py export --archive /你的备份目录/个人法库.zip
.venv/bin/python scripts/transfer_library.py verify --archive /你的备份目录/个人法库.zip
```

导出会锁定相关写入、使用 SQLite 备份并记录文件校验信息。如果提示写入锁忙，等待当前更新结束后重试。导出后旧法库与服务继续保留。

仅对本项目的公开法源目录使用此工具；文件名过滤不能识别任意改名后的私人案卷。校验值用于发现文件损坏，不是发布者数字签名；程序和数据包只从自己的可信备份取得，不公开分发本个人迁移包。

## 2. 在新 Mac 安装

先解开程序文件包，在其根目录运行。示例中的路径需要替换，含空格或中文的路径用引号包住；目标目录必须不存在，父目录必须已经存在。

```sh
python3 scripts/install_mac.py \
  --archive "/你的备份目录/个人法库.zip" \
  --target "/你的安装目录/个人法库" \
  --python "/你的Python目录/bin/python3" \
  --profile search
```

`search` 安装检索和 PDF 所需依赖，受锁定版本约束。`full` 是默认值，安装完整 `requirements.lock.txt`，下载量较大；省略 `--profile` 即选择它。两种模式都会恢复完整公开资料，不因选择检索模式减少资料。

如需联网更新及 Obsidian 盘点页，可在安装时加入这些可选参数：

```sh
  --profile full \
  --treasury-root "/你另行准备的/menglu-legal-treasury" \
  --obsidian-vault "/你的Obsidian库" \
  --soffice "/Applications/LibreOffice.app/Contents/MacOS/soffice"
```

这些参数写入新安装自己的 `config/local-machine.json`。vault 参数只指定 `Songmeng_Law/08_Law/Shared-Library/Live-Inventory.md` 这一托管盘点页；不复制或扫描整个 vault。国家库目录须包含 `sources/legal-tools/国家法律法规数据库MCP/scripts/client.py`，且 `client.FlkClient` 和 `models` 能由新环境导入。

安装器先校验并恢复资料，再直接在最终目录创建 `.venv`，随后安装依赖、检查数据库完整性、用实际保存的条目验证检索和镜像回读。Python 环境不能通过移动安装目录复用；安装成功后请保留路径。

安装结果写入 `verification/install/state.json`。服务文件只生成在 `verification/install/`：检索模式一个 MCP 服务；完整模式仅在更新依赖和国家库客户端检查通过后生成第二个更新服务。此时尚未启用后台服务。18063 已占用不妨碍离线安装和校验。

## 3. 查看分项检查结果

```sh
"/你的安装目录/个人法库/.venv/bin/python" \
  "/你的安装目录/个人法库/scripts/install_mac.py" \
  --target "/你的安装目录/个人法库" --doctor
```

| 字段 | 含义 |
| --- | --- |
| `ready_search` | Python 架构/版本、SQLite、检索依赖和实际库回读通过 |
| `ready_pdf` | pypdf、pdfplumber 在新环境可导入；真实 PDF 抽取仍需另行验收 |
| `ready_doc` | 找到可执行的 LibreOffice；不等于所有旧 DOC 均可转换 |
| `ready_update` | 检索、Scrapling/httpx 和国家库客户端导入就绪；尚未验证联网采集 |
| `port_conflict` | 18063 正被占用，禁止启用第二套同端口服务 |
| `browser_binaries` | `not_checked`，未验证浏览器程序 |

检查同时显示实际 Python 版本、架构、SQLite 版本、缺失依赖和错误。`ready_update=false` 不会阻止检索模式使用，也不会生成更新服务。

## 4. 明确启用登录自动启动

仅在新 Mac 的目标环境检查通过、18063 空闲时执行：

```sh
"/你的安装目录/个人法库/.venv/bin/python" \
  "/你的安装目录/个人法库/scripts/install_mac.py" \
  --target "/你的安装目录/个人法库" --activate
```

也可在首次安装命令末尾加 `--activate`。启用时再次检查环境，将已生成服务文件写入当前用户的 `Library/LaunchAgents`，使用实际用户 ID 注册。已有同名服务文件或已加载同名服务时拒绝，不覆盖、不卸载已有服务。失败时仅卸载本次已经成功注册的服务，删除本次新写入且身份和内容均未变化的服务文件；注册失败的标签不会被卸载。保留安装目录和资料。

检索地址固定为 `http://127.0.0.1:18063/mcp`，只监听本机。MCP 进程退出后会重启；更新服务每 5 分钟核对到期任务，并沿用恢复的调度状态。Mac 关机或休眠时无法工作；登录后补查最近到期任务。注册成功仅表示 LaunchAgent 已注册，输出会明确 `http_ready_verified=false`、`login_restart_verified=false`；尚需在新机器确认工具可用，并重登录验证自动启动。

检查注册状态（不修改服务）：

```sh
launchctl print "gui/$(id -u)/com.chiheng.legal-mcp"
launchctl print "gui/$(id -u)/com.menglu.legal-update"
```

第二条仅用于已生成并启用更新服务的安装。日志在安装目录 `verification/com.*.stdout.log` 和 `verification/com.*.stderr.log`。

## 5. 连接新 Mac 的 Codex

安装器不修改 Codex 配置。确认本机服务已启动后，在新机器先用 `codex mcp list` 检查是否已有 `chiheng-legal`；只有没有同名配置时再运行：

```sh
codex mcp add chiheng-legal --url http://127.0.0.1:18063/mcp
```

上述形式已按本机已安装 Codex 的 `codex mcp add --help` 核对。也可以在 Codex 的 MCP 配置中使用如下片段，已有同名项时先检查原配置，避免重复添加：

```toml
[mcp_servers.chiheng-legal]
url = "http://127.0.0.1:18063/mcp"
```

打开新会话确认 7 个只读工具可见，并分别检查镜像盘点、入库检索和原文片段。loopback 地址仅供该 Mac 使用，云端 ChatGPT 不会因此获得连接。

## 安装失败怎样恢复

依赖下载最长等待 30 分钟，建环境、检查及系统服务命令也有超时。pip 失败或超时后，已恢复资料和 `status=failed` 的状态文件会保留，不启用服务。重跑相同目标会明确拒绝，避免覆盖不完整安装中的资料。保留失败目录用于核对，排查网络/Python/依赖后选择另一个不存在的目标重新安装；不要移动失败的 `.venv` 继续使用，也不要直接删除整套旧安装。

启用失败与安装失败分开：如果安装状态仍为 `complete`，先解决端口或服务名称冲突，再对该目标单独执行 `--activate`。不要为了演练停止原来的在线法库；可保留隔离安装作只读验收。

## 验证边界

迁移、安装流程及服务冲突/回退有临时目录与模拟系统命令测试；实际子进程验证了 SQLite、恢复库检索和镜像回读。当前已验证干净检索/PDF 环境与资料恢复，完整环境的大依赖下载尚未完成独立干净安装验收。未在第二台 Mac 完成全套安装、重登录和持续更新验收，也未自动下载浏览器、复制官方客户端或迁移会员登录。
