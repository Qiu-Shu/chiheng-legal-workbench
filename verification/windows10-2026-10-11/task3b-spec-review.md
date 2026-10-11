# Task 3B 独立规格审查

2026-10-11。结论：CHANGES_REQUIRED。发现四项确定的实现缺口，均可在本机用合成依赖复现，不依赖 Windows 实机推测。此次只新增审查报告，没有修改实现、原 Mac 安装、账号或数据库。

## 必须修复

1. [P1] `windows_browser.py:51` 的参数检查放行 `--openclaw`，允许绕过固定浏览器边界。`vendor/bb-browser/package/dist/cli.js:904` 在 `siteRun` 中进入该选项分支，`:945` 导入 OpenClaw bridge，随后调用独立的 tabs/open/evaluate；`dist/openclaw-bridge-U2GHGPNP.js:29` 使用 `npx openclaw browser`，没有绑定本安装的 CDP 或 profile。即使 wrapper 事先检查 19224 正常，这个后续分支仍会访问另一个浏览器。独立探针确认 `validate_args(['site', 'example/demo', '--openclaw'])` 被接受，真实 CLI 参数解析结果为 `openclaw: true`。最小修复：在进入任何浏览器检查、子进程前拒绝该选项，并补覆盖选项不同位置的离线检查；正常固定 CDP 命令保留。

2. [P1] `windows_browser.py:57` 拦截的顶层 `history` 没有覆盖真实的历史入口 `site recommend`。`vendor/bb-browser/package/dist/cli.js:1140` 将该子命令交给 `siteRecommend`，`:834` 调用 `getHistoryDomains`，`:414` 至 `:460` 查找日常浏览器 History、复制到临时文件并拼接 Unix sqlite3 shell 命令。Windows 分支明确包含 LOCALAPPDATA 下日常 Chrome、Edge 的 Default/History。独立探针确认 `['site', 'recommend']` 和 `['--json', 'site', 'recommend']` 均被 wrapper 接受；以合成 home/LOCALAPPDATA 和文件/命令替身执行实际 `runHistoryQuery`，记录到对合成日常 Chrome History 的复制及 sqlite3 shell 命令。没有读取真实历史。最小修复：在 Windows 受控入口准确拒绝实际历史子路由，覆盖全局选项前置情况；更新文档中的命令名称，不用禁用全部 site 命令替代准确识别。

3. [P2] `windows_browser.py:242` 至 `:243` 的实际 CLI `subprocess.run` 没有 `timeout`。这不满足已批准的“子进程有超时”，命令挂起时 wrapper 可无限等待。独立替身探针调用 `invoke(..., ['--version'])`，实际传给 run 的关键字仅有 `cwd`、`env`。最小修复：给正常受控 CLI 调用设置明确的有限超时，并验证超时时返回安全失败，不输出秘密或结束未知进程。若有长期运行子命令，应明确列为待支持，不能让普通调用失去上限。

4. [P2] 允许的站点管理路线仍使用 shell 和旧用户目录。`vendor/bb-browser/package/dist/cli.js:520` 与 `dist/daemon.js:33` 将 sites 根硬编码为 home/.bb-browser，忽略 wrapper 新设的 BB_BROWSER_HOME；CLI `:754` 把社区目录直接拼到 `git clone` 字符串，`:733` 的 pull 没有超时，`:1166` 至 `:1175` 还会在 site 子命令完成后隐式执行旧目录的后台 pull。独立函数探针将所有文件/命令操作替换为记录器，得到 `git clone https://github.com/epiral/bb-sites.git C:/Synthetic User/.bb-browser/bb-sites`，空格路径未引用且走 shell。最小修复可将尚未迁移的更新子路由明确拒绝并禁用 Windows 隐式更新；需要保留的站点读取路径使用本安装 BB_BROWSER_HOME。若保留更新，则改为参数数组和有限超时。无需增加管理器或扩大站点功能；新增边界应覆盖正常 site 调用不再触发旧目录更新。

## 已核对的要求

| 要求 | 实码与独立检查结果 |
| --- | --- |
| 外部 MCP 独立环境 | `windows_external.py:37` 用固定 runtime 建立 `.venv-mcp1`，离线 wheel 安装启用 require-hashes；`:28` 探针真实导入 FastMCP 并核对 1.28.0；没有安装进主 MCP 2 环境。 |
| 固定运行环境来源 | Node、pnpm 的落盘 SHA-256 已重新计算，与实现常量及已有官方来源记录一致；pnpm 冻结锁哈希为 `36ebe4a184964d23d6857dff3719a04b6043f4fd9d012685213fe8327df44314`。本轮没有联网重新取官方元数据。Python 3.13.16、UTF-8、Asia/Shanghai 支持探针沿用已审查的核心安装器。 |
| 白名单副本及许可 | 当前 vendor 共 52 文件，逐项通过共享 allowed_payload，未发现链接；两类许可与来源说明保留。没有复制 .env、.python-deps、Mac node_modules 或 browser profile。 |
| 认证路径及 Windows 私有读取 | 复制 client 在模块启动读取前调用 access_path；新路径为本安装 private/case-access.env。Windows 分支复用 windows_private.open_file(private=True)，有界读取、错误分类和原认证逻辑仍在。 |
| 本地登录与三步可用性 | 隐藏输入、原子保存、不回退环境 token；server 的认证、检索、对应正文与认证值复核仍完整。令牌存在仅报告 pending，失效提示重新登录。 |
| 国家库封锁 | `scripts/windows_flk_blocked.py` 返回原 FLK_ACCESS_BLOCK 并退出；不导入国家库 vendor client，不自动联网。 |
| 宿主配置 | 独立 stdio TOML 指向最终 SDK1 环境；检查同名连接，不写宿主配置。 |
| 浏览器已实现的边界 | 固定 127.0.0.1:19224、新私有 profile、清 hub/Node 注入环境、PID/创建时间/命令/端口归属检查、未知和陈旧 daemon 拒绝、`--no-chrome`、显式 CDP 失败拒绝回退均有实现。上列旁路仍需封闭。 |
| 分项状态与能力限制 | 核心 doctor 单列 external；外部失败不会抬升为 ready。文档明确 Win10 浏览器/Playwright 支持限制与原生待验；没有把本机检查称为原生通过。 |

## 本次独立执行

- 使用项目 `.venv/bin/python -B`，以 socket.connect/connect_ex 拒绝网络，执行外部专项 22 项：20 通过，2 项 Windows ACL 原生测试跳过。
- 使用本机已有 Node 执行 `tests/windows_bb_boundary.mjs`：5 项通过。它们执行副本函数并替换依赖，没有连接浏览器。
- 将既有恢复/三步测试重定向到复制 client/server：首轮 48 项中 47 通过，1 项旧测试仍断言默认路径为 vendor/.env，因本任务已要求 private/case-access.env 而失败。排除该过时默认路径断言后，47 项全部通过；新默认路径和启动前生效由外部专项独立覆盖。旧测试便携改造已明确留在 Task 4，未将其算作本轮实现缺陷，也未宣称本轮原样重跑 48 项全过。
- 重新计算固定 Node/pnpm archive、冻结锁及补丁身份；逐项核对 vendor 白名单。没有执行 Windows 二进制。
- 额外离线探针复现上述参数放行、真实历史路径选择、历史复制/shell 路由、站点 clone 拼接以及缺少 timeout。所有副作用均为替身记录。
- 未自行重跑 607 项全量；本报告不把实现者全量日志作为独立执行证据。

## 范围与后续

Windows ACL、PowerShell/CIM、实际 Node/pnpm 安装、真实账号三步、专用浏览器启动与宿主导入仍属 Task 5 原生验收。没有 Windows 机器不是本次 CHANGES_REQUIRED 的原因。Task 4 总包、Skill 副本和旧测试便携路径不纳入本轮阻断。

Ponytail review 未发现需要删除的独立过度设计，建议的修复保持现有小型入口结构。net: -0 lines possible。报告文字使用 Humanizer 整理，技术证据和缺陷等级不因文字编辑改变。

## 修复复核，2026-10-11

当前规格结论：PASS。上方首轮 CHANGES_REQUIRED 及其证据保留；四项阻断均已修复。本结论限 Task 3B 工程规格和本机离线合成验证，不表示 Windows 原生验收通过。

| 首轮问题 | 本次独立复核 |
| --- | --- |
| 1：OpenClaw 旁路 | `windows_browser.py:52` 至 `:54` 在参数检查首段拒绝 --openclaw，覆盖前置、插入、尾部及等号形式；invoke 在验证补丁、连接浏览器和启动子进程前执行该检查。拒绝前无副作用的专项通过。 |
| 2：实际历史入口未拦 | `windows_browser.py:57` 至 `:70` 按固定 CLI 的位置参数规则跳过带值选项，识别 site recommend/update。额外以真实 CLI parseArgs 函数对照 512 种危险路由参数组合，全部被 wrapper 拒绝；组合覆盖各带值全局选项、选项值恰为 site/recommend/update、全局选项前置或插入。site search update 等正常查询仍允许。 |
| 3：CLI 无超时 | `windows_browser.py:256` 至 `:261` 设定 120 秒并把 TimeoutExpired 转换为固定安全错误。专项和额外探针确认正常成功、非零退出码 7 保留、实际 tab list 路线超时安全失败；错误不包含合成命令、stdout 或 stderr，超时不调用 remember_daemon。 |
| 4：旧目录与隐式更新 | CLI `:520`、daemon `:33` 的 sites 根优先使用 BB_BROWSER_HOME；CLI `:1166` 在 Windows 跳过 silentUpdate，wrapper 拒绝未迁移的 site update。执行实际副本函数的合成检查确认两种 sites 根不咨询旧 home，正常 site list 不执行更新文件探测。历史推荐和更新路由在进入 CLI 前已拒绝；正常 site 读取/执行保留。 |

本次重新执行外部专项 25 项：23 通过、2 项 Windows ACL 原生测试跳过；JS 实际函数边界检查 8 项全部通过。Python 测试继续拦截 socket.connect/connect_ex；没有官网、真实浏览器、账号或系统服务访问。另独立检查修复前后 diff：CLI 仅变更 sites 根和 silentUpdate 的 Windows 条件，daemon 仅变更 sites 根，没有扩大成管理器。

重新计算并验证当前补丁身份：CLI 为 `3f496cf5b832ae3e83246d87da82617060d2491f041b773b1ab4360d5bc5fc5d`，daemon 为 `34e83e7b63e007afd0126e1cfd5331c81034d80908d9df1e93adb554dc6fd7f7`，与 helper 常量和来源说明一致。文档现在准确说明被拒绝的实际子路由、120 秒限制、专用 sites 路径和原生待验范围。

本次没有独立重跑所报告的 610 项全量，也没有重跑案例恢复 47 项；原首轮的执行口径保持不变。Task 4 旧测试默认路径与最终打包，以及 Task 5 原生 Windows 验收继续待完成。Ponytail 复核未发现新增不必要抽象；净可删冗余为 0 行。
