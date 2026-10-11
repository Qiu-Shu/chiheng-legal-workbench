# Task 4 Windows 个人总包实施交接

2026-10-11。状态：待规格与质量审查。候选已完成 Mac host 独立恢复验证；原生 Windows 验收仍属于 Task 5。主代理要求保持冻结，统一处理规格审查发现的问题后再发布最终包。

## 当前候选与已知待处理项

候选目录：`../../outputs/chiheng-windows10-2026-10-11-pevq61o5`（相对项目根）。ZIP 名称为 `持衡-Windows10-x64-个人迁移总包.zip`，大小 255543894 字节，SHA-256：

`d963f75a73fd72ea6876f23422d3ddfcbabb63afee6d27f6c949d845b1d14187`

同目录有 SHA256.txt、内容清单.json 和先读我-迁移说明.md。451 个外层载荷加 manifest.json，共 452 个 ZIP 成员。旧的 089ip81e、qcqh_wqg 是未交付构建候选，不能作为最终交付链接。

目前有两项待审查后统一处理：

- 本候选生成后，测试 YAML helper 又补了纯 JSON 类型兼容：原 Ruby safe_load/JSON.generate 拒绝 Date、Set 和 Infinity，PyYAML safe_load 本身允许；新用例先红，再用 json.dumps(allow_nan=False) 拒绝这些值，已绿。修改仅为 tests/test_p1.py 和 tests/test_windows_delivery.py，尚未进入此候选 ZIP。发布前必须重打并核对。
- 主代理发现旧测试尚有 POSIX 专属断言（mac installer 的 getuid、模拟法庭权限/硬链接等），正在规格审查确认 Windows 分流范围。619 项结果是独立 Mac host 检查，不是 Windows 全套可运行的实测证明。必须保留对应安全断言并正确分流，不能大面积跳过模拟法庭行为测试。

## 实现范围

新增 `scripts/build_windows_delivery.py`，复用 library_transfer.export_library/verify_archive 及安装器白名单。唯一新目录输出，不调用 build_release.main、不覆盖历史 ZIP。普通载荷复制前后核对长度和 SHA，导出资料由既有锁与快照机制保护；清单逐文件检查，拒绝额外/变化文件、符号链接和不允许的路径。

安装器白名单只增加三份既有测试所需资产：source/dist/cn-litigation-redteam.zip、source/upstream/original/LICENSE、NOTICE，以及 runtime/wheels-dev 下的 wheel。没有开放整个 upstream 或 source/config。外层插件 .mcp.json 仅通过其明确路径进入。launcher 复用原 scripts/install_windows.cmd，不新增第二套启动逻辑。

新增 tests/test_windows_delivery.py，覆盖白名单、敏感/会话排除、源变化、符号链接、清单失败、YAML 安全与便携、vendor 路径及插件连接定义。新增 scripts/test_windows_offline.py 作为主环境离线测试入口；ReportLab 为可选开发依赖，requirements-windows-dev.lock.txt 固定官方 wheel 哈希。

修改 tests/test_p1.py：由 Ruby 改为已有 PyYAML，拒绝别名和不安全对象；纯 JSON 类型补丁状态见上文。修改 tests/test_rmfyalk_recovery.py、test_rmfyalk_recovery_server.py、test_vendor_download.py：使用包内 vendor，依赖只选本安装的独立 MCP1 或明确测试环境，启动前将 windows_case_access.access_path 重定向到合成私有文件，保留两个 SDK 缓存恢复/先后加载隔离断言。POSIX FIFO/mode/open flags 检查保留并在 Windows 明示跳过，原生 ACL 测试独立保留；其他旧平台断言待规格审查统一处理。

vendor/treasury/sources/china-law 新增两脚本、README、三个必要 JSON 与来源说明。没有复制其全部 Skills。README 许可徽章与当前上游根许可不一致，只作个人已有副本迁移，未声明公开再分发许可已完成。

新增中文 docs/windows10-migration-guide.md，说明摘要核对、完整解压、新目录、Y/n 自启动、分项状态、手动 Skill/MCP 导入、Obsidian 选择、新机本人登录、独立解释器和真实验收。没有默装宿主/未知浏览器，未改系统代理、注册表或全局执行策略。

## Skill 与插件副本

仅修改 `verification/windows10-2026-10-11/windows-copies` 下交付副本。持衡增加 windows-local.md、入口和模拟法庭交叉链接、coverage 历史 Mac 注释；原分析、事实、材料哈希、引用、自认审批、审计、逐轮和复练规则保留。插件内嵌持衡同步，原身份、HTTP 配置和元数据保留。萌律的固定 Mac 路径和旧登录说明替换为实际 target/state、双环境、唯一 private/case-access.env、当前宿主认证/检索/正文三步、FLK blocked 优先和未携带工作流边界。Scrapling 官方 Skill 保留原件。

独立应用复测由主代理组织，指出的共享检索步骤与 FLK blocked 冲突已修复；覆盖历史结果不能表示 Windows 通过、认证值仅收 RMFYALK_TOKEN 原值、不造取值入口等说明已加入。最终副本已冻结供主代理核对。Skill 验证器持衡与萌律均通过。

memory 只含本项目 Index.md 与 Summary.md，指向安装内路径。资料统计不硬编码旧数值。依据主代理实际手动读取的当前项目小笔记和本次导出状态；本轮没有收到记忆钩子实际输出，未宣称钩子运行。

## 红绿与恢复证据

最初 6 个新边界测试：1 通过、4 预期失败、1 白名单拒绝错误；失败为缺少 builder、新精确白名单和 Ruby 外部调用。逐项实现后 6 通过。包内 vendor 路径断言先因原 Mac 路径失败，改造后 50 项案例/SDK 测试通过。插件 .mcp.json 排除先复现失败，修正后通过。YAML Date/Set/Infinity 用例先失败再通过。初始红输出保留于任务工具记录；当前 9 项绿结果在 task4-focused-green.log（不含稍后的纯 JSON 三输入追加，追加单项已执行通过）。

源码阶段离线 617 项：605 通过、12 原生待验，见 task4-source-offline.log。最终候选在新中文含空格目录恢复，使用此轮从 PyPI 按 Windows 锁同版本重建的 Mac Python 3.12 host 环境（排除无法在 Mac 执行的 pywin32），无原 Mac .venv/.python-deps 复制；ReportLab 从包内 wheel 安装。首次 SDK1 宽范围解析结果随后按锁固定，独立最终环境从固定版本重建。下载/安装日志在 clean 目录 install-main.log、install-mcp1.log，host pins 同目录保存，不进入 Windows 包。

恢复目标为 `../../outputs/windows-clean-restore-dfhg512c/持衡 最终独立恢复`。新 host 依赖位于同一 clean 工作区的“持衡 独立恢复/.venv、.venv-mcp1”，是本轮新建环境，非原 Mac 安装。通过 sitecustomize audit hook 拒绝旧工程 ROOT、旧 Treasury、原已安装 Skills 和旧 Mac 交付目录的文件读取，并拒绝 socket.connect；主测试入口另外阻止实时 socket/fetch。解释器标准库来自应用自带 host runtime，未将其装入迁移 ZIP。

实际结果：

- 外层全部载荷与 manifest 校验成功，插件连接定义存在。
- 590 个内层载荷逐长度/SHA-256 一致；恢复数据库全部核心表逻辑摘要与导出一致，versions 49、search_index 49、provenance 49、audit 100、published 0、withdrawn 0。
- 49 个版本的片段与来源卡逐一验证版本 ID、来源链接、正文 SHA、review_state 与 missing_fields；安装器烟雾验证公开原件和离线镜像检索。
- 镜像 2190 版本、77809 文本单元，保持 unverified_mirror。
- 包内完整 Python 离线套件 619 项：607 通过、12 原生待验；JS 真实 vendor 函数合成检查 12 通过。

完整结果在 task4-final-restoration.json，实际日志在 clean 目录 final-offline.log、final-js.log、final-all-cards.log。最初全来源卡验证器错用了不存在的 legal_mcp.store，基础烟雾通过后 harness 报错；已改为 readonly LegalStore，单独复验全部49通过，原 final-cards.log 保留该失败。此错误没有修改产品代码或库。

## 保留与限制

task4-before 保存受影响原源码与摘要。131 个先前跟踪的原 Skill、插件、vendor 文件逐哈希未变，见 task4-preservation-check.json。原 Mac 已安装 Skills、原插件、真实凭据、浏览器、主数据库内容与历史输出未修改；仅本任务必要源码/测试/文档及新增明确 vendor 副本变更。没有 Git init、commit、worktree、账号上传或发布。

Windows 10 x64 Python/ACL/PowerShell/COM、目标机真正安装、计划任务和重新登录、实际宿主 MCP、本人新登录及案例三步、浏览器正常命令、PDF/DOC 实际转换仍待 Task 5。浏览器依赖需要冻结联网重建；当前 Playwright 官方列 Windows 11+，未承诺 Windows 10。没有全国法律全覆盖、法律结论正确性或真实律师审批验收结论。
